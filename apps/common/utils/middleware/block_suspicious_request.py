"""
Aplicacion de los bloqueos por IP.

Esto es **mitigacion de ruido, no seguridad**. Su unico trabajo es que los
escaneres automaticos dejen de consumir recursos. Ninguna decision de
seguridad debe apoyarse aqui, y por eso el criterio es *fallar abierto*: ante
cualquier duda, dejar pasar.

Lo que fallaba
--------------
* **La lista blanca no se consultaba.** Anadir una IP no la desbloqueaba,
  porque quien aplica el bloqueo es este middleware y no la miraba. Era el
  remedio documentado del proyecto, y no servia.
* **La IP se resolvia distinto aqui que al crear el bloqueo**, asi que uno
  guardaba bajo una IP y el otro buscaba por otra.
* **El bloqueo crecia sin techo.** Cada peticion sumaba otro intervalo, asi
  que un bot a diez peticiones por segundo lo convertia en permanente -- y a
  un usuario legitimo pillado por un falso positivo, tambien.
* **La lista de rutas crecia sin limite** dentro del JSON de la fila: un bot
  insistente podia inflarla hasta pesar megabytes.
* **Un administrador podia quedarse fuera de su propio panel** por teclear
  mal una URL.
* **La respuesta contaba el bloqueo.** Un 403 que dice "esta IP esta
  bloqueada por actividad sospechosa" y ademas ensena el numero de intentos y
  la hora de expiracion le regala al escaner justo lo que necesita: que hay un
  bloqueo por IP, que su sonda dio en la trampa y cuando volver. Ahora
  responde el mismo 404 que cualquier otra pagina que no existe -- la misma
  regla que ya sigue el admin (invariante 7 de ``CLAUDE.md``): un 403
  confirma; un 404 no dice nada.

Ver ``apps/common/utils/client_ip.py`` para la resolucion de la IP y las
exenciones, que ahora viven en un solo sitio.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.utils import OperationalError, ProgrammingError
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.common.utils.blocking import block_until, note_attempt
from apps.common.utils.client_ip import get_client_ip, is_exempt
from apps.common.utils.models import IPBlockedModel
from apps.common.utils.views import is_safe_path

logger = logging.getLogger(__name__)

try:
    template_name = settings.ERROR_TEMPLATE
except AttributeError:
    template_name = 'errors_template.html'
except SystemExit:
    raise
except Exception as error:
    logger.error('An unexpected error occurred: %s', error)
    template_name = 'errors_template.html'

class DetectSuspiciousRequestMiddleware:
    """Deja pasar, o devuelve 404 si la IP esta bloqueada ahora mismo."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.block_base = timedelta(
            minutes=getattr(settings, 'IP_BLOCKED_TIME_IN_MINUTES', 15)
        )

    def __call__(self, request):
        path = request.path or ''

        # 1) Rutas inocuas (estaticos, extensiones, UUID): ni se mira.
        try:
            if is_safe_path(path):
                return self.get_response(request)
        except Exception:
            # Un fallo detectando no puede convertirse en un bloqueo.
            return self.get_response(request)

        # 2) Exenciones: lista blanca y personal interno autenticado. Va antes
        #    de tocar la tabla de bloqueos, que es lo que hace que anadir una
        #    IP a la lista blanca funcione de verdad.
        try:
            if is_exempt(request):
                return self.get_response(request)
        except Exception:
            logger.exception('Could not evaluate the block exemptions')
            return self.get_response(request)

        client_ip = get_client_ip(request)

        try:
            blocked_entry = IPBlockedModel.objects.filter(
                current_ip=client_ip,
                is_active=True,
                blocked_until__gte=timezone.now(),
            ).first()
        except (ProgrammingError, OperationalError):
            return self.get_response(request)

        if not blocked_entry:
            response = self.get_response(request)

            if 400 < response.status_code < 500:
                logger.info(
                    'Error %s for IP %s', response.status_code, client_ip
                )

            return response

        self._note_attempt(blocked_entry, request)

        # Toda la informacion del bloqueo se queda aqui, en el log del
        # servidor, que es donde sirve para diagnosticar. La respuesta no
        # lleva nada de esto.
        logger.warning(
            'Blocked IP %s attempted access to %s (attempt %s, until %s).',
            client_ip,
            path,
            (blocked_entry.session_info or {}).get('attempt_count', 1),
            blocked_entry.blocked_until,
        )

        return self._not_found(request)

    def _not_found(self, request):
        """
        La respuesta para una IP bloqueada: un 404 y nada mas.

        Es **exactamente** la misma pagina que devuelve ``handler404`` para
        cualquier ruta que no existe, y a proposito: si el bloqueo tuviera su
        propia pagina, su propio codigo o su propio texto, distinguir las dos
        seria trivial y el escaner sabria que dio en la trampa.

        Sigue siendo una respuesta util para quien la lee sin ser un bot --
        pagina de error del producto, con su marca y su "no encontrado", no
        una pantalla en blanco-- pero no dice que exista un bloqueo, ni
        cuantos intentos van, ni cuando caduca. Un usuario legitimo pillado
        por un falso positivo se diagnostica desde ``IPBlockedModel`` y desde
        el log de arriba, no desde la pantalla del navegador.
        """
        return render(
            request,
            template_name,
            status=404,
            context={
                'exception': '',
                'title': _('Error 404'),
                'error': _('Page not found'),
                'status': 404,
                'error_image': (
                    'https://geausa.propensionesabogados.com/public/static/'
                    'assets/imgs/status_errors/404-error.svg'
                ),
            },
        )

    def _note_attempt(self, blocked_entry, request):
        """
        Anota el intento y alarga el bloqueo, pero con techo.

        La duracion sale de ``blocking.block_until()``, la misma que usa la
        vista trampa: duplica en cada intento y no pasa de ``MAX_BLOCK``.
        Antes aqui se sumaba un intervalo fijo y alli se multiplicaba, asi que
        el mismo escaner recibia castigos distintos segun por donde entrara.
        """
        try:
            with transaction.atomic():
                info = note_attempt(blocked_entry.session_info, request)

                blocked_entry.session_info = info
                blocked_entry.blocked_until = block_until(
                    info['attempt_count'],
                    self.block_base,
                    current=blocked_entry.blocked_until,
                )
                blocked_entry.save(
                    update_fields=['session_info', 'blocked_until']
                )
        except Exception as error:
            # Que no se pueda anotar el intento no cambia la decision.
            logger.exception('Could not record the blocked attempt: %s', error)
