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

from apps.common.utils.blocking import capped_until, note_attempt
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
    """Deja pasar, o devuelve 403 si la IP esta bloqueada ahora mismo."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.block_step = timedelta(
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

        logger.warning('Blocked IP %s attempted access.', client_ip)

        return render(
            request,
            template_name,
            status=403,
            context={
                'exception': _(
                    'This IP is temporarily blocked due to suspicious '
                    'activity.'
                ),
                'title': _('Error 403'),
                'error': _('Access denied due to suspicious activity.'),
                'status': 403,
                'error_image': (
                    'https://geausa.propensionesabogados.com/public/static/'
                    'assets/imgs/status_errors/403-error-forbidden.svg'
                ),
                'attempt_count': (blocked_entry.session_info or {}).get(
                    'attempt_count', 1
                ),
                'blocked_until': blocked_entry.blocked_until,
            },
        )

    def _note_attempt(self, blocked_entry, request):
        """
        Anota el intento y alarga el bloqueo, pero con techo.

        El techo es lo importante: antes cada peticion sumaba otro intervalo
        sin limite, asi que insistir lo volvia perpetuo. Ahora insistir no
        pasa de ``MAX_BLOCK`` desde ahora.
        """
        try:
            with transaction.atomic():
                blocked_entry.session_info = note_attempt(
                    blocked_entry.session_info, request
                )
                blocked_entry.blocked_until = capped_until(
                    self.block_step, current=blocked_entry.blocked_until
                )
                blocked_entry.save(
                    update_fields=['session_info', 'blocked_until']
                )
        except Exception as error:
            # Que no se pueda anotar el intento no cambia la decision.
            logger.exception('Could not record the blocked attempt: %s', error)
