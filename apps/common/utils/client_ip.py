# apps/common/utils/client_ip.py
"""
De donde viene una peticion, y si hay que dejarla en paz.

Habia **dos** respuestas distintas a la misma pregunta, y esa era la raiz de
casi todo lo que fallaba en la mitigacion anti-escaneo:

* ``HttpRequestAttackView`` -- la que crea los bloqueos -- leia
  ``X-Forwarded-For``, y de paso consultaba la lista blanca.
* ``DetectSuspiciousRequestMiddleware`` -- la que los aplica -- leia
  ``REMOTE_ADDR`` a secas, y **no** consultaba la lista blanca.

De ahi salian dos problemas reales:

1. **La lista blanca no servia de nada.** Anadir una IP no la desbloqueaba,
   porque quien decide si te deja pasar es el middleware, y el middleware no
   la miraba. La documentacion del proyecto recomienda justo eso como
   remedio, y no funcionaba.

2. **Cualquiera podia hacer que bloquearan a otro.** ``X-Forwarded-For`` lo
   pone el cliente. Basta con mandar la cabecera con la IP de la victima y
   pedir una ruta trampa para que quede bloqueada en su lugar. Un bloqueo
   ajeno, provocado a voluntad, desde fuera.

Aqui hay una sola respuesta, y por defecto **no se cree a la cabecera**: se
usa ``REMOTE_ADDR``, que la pone el servidor web y el cliente no controla. Si
la plataforma se pone algun dia detras de un proxy o un CDN de verdad, se
activa con ``TRUSTED_PROXY_DEPTH`` -- cuantos saltos de confianza hay -- y se
toma la IP en esa posicion contando desde el final, que son los que el proxy
anadio y no los que el cliente pudo inventarse.

Recordatorio de por que esto no es un control de seguridad: bloquear por IP
solo estorba a los escaneres automaticos. Ante la duda, dejar pasar.
"""

import logging
from ipaddress import ip_address

from django.conf import settings

logger = logging.getLogger(__name__)

UNKNOWN_IP = '0.0.0.0'


def trusted_proxy_depth() -> int:
    """
    Cuantos proxies propios hay delante de la aplicacion.

    Cero -- el valor por defecto -- significa que la aplicacion recibe las
    conexiones directamente y ``X-Forwarded-For`` no es de fiar.
    """
    try:
        return max(0, int(getattr(settings, 'TRUSTED_PROXY_DEPTH', 0) or 0))
    except (TypeError, ValueError):
        return 0


def get_client_ip(request) -> str:
    """
    La IP del cliente, sin creerse lo que el cliente cuenta de si mismo.

    Returns:
        str: la IP, o ``0.0.0.0`` si no se puede determinar.
    """
    depth = trusted_proxy_depth()

    if depth:
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
        chain = [part.strip() for part in forwarded.split(',') if part.strip()]

        # Los ultimos `depth` los anadieron nuestros proxies; el cliente solo
        # controla lo que va antes. Se toma el primero que ellos anadieron.
        if len(chain) >= depth:
            candidate = chain[-depth]

            try:
                return str(ip_address(candidate))
            except ValueError:
                logger.warning(
                    'Malformed X-Forwarded-For entry: %r', candidate
                )

    remote = request.META.get('REMOTE_ADDR', '')

    try:
        return str(ip_address(remote))
    except ValueError:
        return UNKNOWN_IP


def is_exempt(request) -> bool:
    """
    Si esta peticion no debe bloquearse pase lo que pase.

    Dos casos, y los dos son de disponibilidad, no de seguridad:

    * **La lista blanca.** Es el remedio documentado cuando alguien queda
      bloqueado por error; tiene que funcionar en los dos lados.
    * **El personal interno autenticado.** Que un administrador se quede
      fuera de su propio panel por teclear mal una URL es exactamente el
      autobloqueo que hay que evitar, y quien ya ha pasado por el login y el
      segundo factor no es el escaner del que esto protege.
    """
    user = getattr(request, 'user', None)

    if user is not None and getattr(user, 'is_authenticated', False):
        if user.is_active and (user.is_staff or user.is_superuser):
            return True

    return is_whitelisted(get_client_ip(request))


def is_whitelisted(client_ip: str) -> bool:
    """True si la IP esta en la lista blanca. Ante cualquier fallo, True."""
    from django.db.utils import OperationalError, ProgrammingError

    from .models import WhiteListedIPModel

    if not client_ip:
        return False

    try:
        return WhiteListedIPModel.objects.filter(
            current_ip=client_ip
        ).exists()
    except (ProgrammingError, OperationalError):
        # Sin tabla (durante una migracion, por ejemplo) no se puede saber.
        # Se falla ABIERTO: esto solo es mitigacion de ruido, y dejar a la
        # gente fuera por un fallo de base de datos seria mucho peor.
        logger.warning('Whitelist unavailable; letting the request through')
        return True
