# apps/common/utils/middleware/block_bots.py
"""
Lo que se decide mirando sólo el ``User-Agent``.

Aquí conviven dos cosas que **no son la misma** y que antes se trataban igual,
con el mismo 403 y el mismo cuerpo de texto:

**1. Rastreadores que se identifican y respetan las reglas.** GPTBot,
ClaudeBot, PerplexityBot, AhrefsBot… Que pasen o no es una decisión de
*política* --si se quiere que el contenido del despacho alimente modelos y
herramientas de SEO-- y no un asunto de seguridad. Se les contesta **403**, que
es lo correcto: dice «no, y a propósito», el rastreador lo entiende y deja de
volver. Un 404 aquí sería mentira y los haría reintentar.

**2. Herramientas de ataque que se identifican solas.** sqlmap, nikto, nmap,
masscan, zgrab. Que un escáner anuncie su nombre en el ``User-Agent`` es
descuido de quien lo lanza, pero cuando pasa es la señal más limpia que hay:
nadie usa sqlmap por error. A éstos **no** se les contesta 403 --confirmar el
bloqueo le dice al operador que hay filtro por agente y que basta con cambiar
la cadena-- sino el mismo 404 silencioso que el resto de la capa, y además se
les abre bloqueo por IP. Es la misma regla del invariante 20: un 403 se
anuncia; un 404 no dice nada.

La distinción importa porque la mezcla anterior fallaba por los dos lados: le
regalaba información al que ataca, y a la vez le devolvía a un rastreador
educado un cuerpo de texto plano en lugar de una respuesta clara.

Sobre falsos positivos
----------------------
La lista de escáneres son nombres de herramienta, no palabras del idioma:
``sqlmap`` no aparece en el agente de ningún navegador. Aun así, se exige que
el nombre aparezca como **token**, no como subcadena suelta, por la misma
razón por la que la trampa de rutas empareja segmentos completos: fue
exactamente así como ``env`` acabó bloqueando ``/envio/``.
"""

import logging
import re

from django.http import HttpResponseForbidden

logger = logging.getLogger(__name__)


#: Rastreadores declarados. Decisión de política, no de seguridad: se les dice
#: que no y se les dice claramente.
POLICY_BOTS = [
    'GPTBot',
    'Google-Extended',
    'ClaudeBot',
    'Claude-User',
    'Claude-SearchBot',
    'PerplexityBot',
    'Perplexity-User',
    'Meta-ExternalAgent',
    'Applebot',
    'Applebot-Extended',
    'facebookexternalhit',
    'ia_archiver',  # Alexa
    'MJ12bot',
    'AhrefsBot',
    'SemrushBot',
    'DotBot',
    'Baiduspider',
    'YandexBot',
    'Sogou',
    'Exabot',
]

#: Herramientas de ataque que se anuncian. Nadie las ejecuta sin querer.
SCANNER_SIGNATURES = [
    'sqlmap',
    'nikto',
    'nmap',
    'masscan',
    'zgrab',
    'zmap',
    'nessus',
    'openvas',
    'acunetix',
    'nuclei',
    'wpscan',
    'dirbuster',
    'gobuster',
    'feroxbuster',
    'ffuf',
    'hydra',
    'havij',
    'arachni',
    'metasploit',
    'commix',
    'xsser',
]


def _token_regex(names):
    """
    Empareja el nombre como token, no como subcadena.

    Un ``User-Agent`` es una lista de tokens separados por espacios, barras,
    paréntesis y comas. Buscar la subcadena suelta es lo que convierte a
    ``nmap`` en parte de cualquier palabra que lo contenga, y esa clase de
    error ya costó un autobloqueo en la trampa de rutas.
    """
    alternation = '|'.join(re.escape(name) for name in names)

    return re.compile(
        r'(?:^|[\s/;,()\[\]-])(?:' + alternation + r')(?:[\s/;,()\[\]-]|$)',
        re.IGNORECASE,
    )


POLICY_REGEX = _token_regex(POLICY_BOTS)
SCANNER_REGEX = _token_regex(SCANNER_SIGNATURES)


class BlockBadBotsMiddleware:
    """Corta rastreadores por política y escáneres declarados por seguridad."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user_agent = request.META.get('HTTP_USER_AGENT', '') or ''

        if user_agent and SCANNER_REGEX.search(user_agent):
            return self._handle_scanner(request, user_agent)

        if user_agent and POLICY_REGEX.search(user_agent):
            # 403 y con motivo: un rastreador que respeta las reglas necesita
            # entender que la respuesta es deliberada para dejar de volver.
            return HttpResponseForbidden('Forbidden: bot blocked.')

        return self.get_response(request)

    def _handle_scanner(self, request, user_agent):
        """
        Un escáner declarado: se le abre bloqueo y se le contesta 404.

        El bloqueo se abre aquí y no se deja para la trampa de rutas porque
        estas herramientas empiezan por rutas que **sí** existen --midiendo
        respuestas y tiempos-- antes de pedir nada que salte la trampa. Cuando
        llegasen a ella ya habrían recorrido medio sitio.

        Todo el manejo va en un ``try``: la detección es una mejora, y si algo
        falla aquí lo que corresponde es dejar pasar la petición, no tumbarla.
        """
        from apps.common.utils.client_ip import get_client_ip, is_exempt

        try:
            if is_exempt(request):
                return self.get_response(request)

            self._record(request, get_client_ip(request), user_agent)
        except Exception:  # noqa: BLE001
            logger.exception('Could not record the scanner signature')

        # El mismo 404 que el resto de la capa, sin cuerpo propio: decirle
        # «bot bloqueado» le confirma que hay filtro por agente, y cambiar la
        # cadena del agente cuesta un parámetro.
        from apps.common.utils.middleware.block_suspicious_request import \
            DetectSuspiciousRequestMiddleware

        return DetectSuspiciousRequestMiddleware(self.get_response)._not_found(
            request)

    def _record(self, request, client_ip, user_agent):
        """Abre o alarga el bloqueo por firma de escáner."""
        from datetime import timedelta

        from django.conf import settings
        from django.db import transaction
        from django.utils import timezone

        from apps.common.utils.blocking import (apply_to_entry, block_until,
                                                note_attempt)
        from apps.common.utils.models import IPBlockedModel

        if not client_ip:
            return

        base = timedelta(
            minutes=getattr(settings, 'IP_BLOCKED_TIME_IN_MINUTES', 15))

        signature = SCANNER_REGEX.search(user_agent)
        matched = signature.group(0).strip(' /;,()[]-') if signature else ''

        logger.warning(
            'Scanner signature %r from IP %s on %s',
            matched, client_ip, request.path,
        )

        info = {
            'attempt_count': 1,
            'client_ip': client_ip,
            'paths': [request.path],
            'user_agent': user_agent,
            'method': request.method,
            'scanner_signature': matched,
            'timestamp': timezone.now().isoformat(),
        }

        with transaction.atomic():
            entry, created = IPBlockedModel.objects.get_or_create(
                current_ip=client_ip,
                defaults={
                    'reason': IPBlockedModel.ReasonsChoices.SCANNER_SIGNATURE,
                    'blocked_until': block_until(1, base),
                    'session_info': info,
                },
            )

            if not created:
                info = note_attempt(entry.session_info, request)
                entry.session_info = info
                entry.blocked_until = block_until(
                    info['attempt_count'], base, current=entry.blocked_until)
                entry.is_active = True

            apply_to_entry(entry, info, request, pattern=matched)
            entry.save()
