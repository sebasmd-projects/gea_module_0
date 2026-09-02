# apps/common/utils/login_attempts.py
"""
Un solo contador de intentos fallidos para todas las puertas del acceso.

En esta plataforma se puede entrar de tres formas --contraseña, código enviado
al correo y, si lo hay, el segundo factor--, y hasta ahora sólo la primera
contaba. `django-axes` se entera de un fallo porque lo dispara `authenticate()`,
y los otros dos caminos no pasan por ahí: se comprueban a mano contra un hash
guardado en la sesión o contra el dispositivo TOTP.

Eso dejaba dos agujeros del mismo tamaño. Quien probara códigos de seis cifras
tenía barra libre --el tope de cinco intentos por código se esquiva pidiendo
otro--, y quien probara segundos factores también. Peor aún: el camino más
barato para el atacante era justo el que no contaba, así que el freno de la
contraseña sólo estorbaba a quien de verdad la había olvidado.

Aquí viven las dos operaciones que faltaban, escritas una vez:

* `note_failure()` dispara la señal ``user_login_failed``, que es de donde axes
  toma nota. No se escribe en sus tablas a mano: la señal es su interfaz
  pública y respeta sus ajustes --la pareja (IP, usuario), la lista blanca, la
  espera-- sin que haya que replicar ninguno.
* `is_locked_out()` pregunta si esa pareja ya está bloqueada, para poder
  negarse **antes** de comparar nada. Sin esta llamada, un bloqueo apuntado no
  frena nada: sólo queda anotado.

Las dos normalizan el usuario igual que `axes_hooks.username()`, y por el mismo
motivo: si «Ana» y « ana » contaran por separado, cada mayúscula sería una
cuenta atrás nueva y el tope no se alcanzaría nunca.
"""

import logging

from axes.handlers.proxy import AxesProxyHandler
from django.contrib.auth.signals import user_login_failed

logger = logging.getLogger(__name__)


def _credentials(username: str) -> dict:
    """
    Lo que axes espera recibir: un diccionario con el usuario dentro.

    Se normaliza aquí y no en quien llama porque son tres sitios distintos y
    basta con que uno se olvide para que ese camino lleve su propia cuenta.
    """
    return {'username': (username or '').strip().casefold()}


def note_failure(request, username: str, *, reason: str = '') -> None:
    """
    Apunta un intento fallido, venga por donde venga.

    Args:
        request: la petición de acceso; de ella salen la IP y el agente.
        username: quien intentaba entrar. Si va vacío, el intento se guarda
            igualmente contra la IP: perder el detalle es mejor que perder el
            intento.
        reason: qué falló, sólo para el log. No llega a axes.
    """
    logger.info(
        'Failed login attempt (%s) for %r', reason or 'unspecified', username)

    user_login_failed.send(
        sender=__name__,
        credentials=_credentials(username),
        request=request,
    )


def is_locked_out(request, username: str) -> bool:
    """
    Si esta pareja (IP, usuario) ya agotó sus intentos.

    Se pregunta **antes** de comprobar un código o un segundo factor. Hacerlo
    después sería contar los fallos sin llegar a frenar nada.
    """
    return not AxesProxyHandler.is_allowed(request, _credentials(username))
