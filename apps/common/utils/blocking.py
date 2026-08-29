# apps/common/utils/blocking.py
"""
Politica de los bloqueos por IP: cuanto duran y que se guarda de ellos.

Vive aparte porque la usan los dos extremos -- la vista que crea el bloqueo y
el middleware que lo aplica -- y tenerla duplicada era justo lo que hacia que
se comportaran distinto. Ademas, meterla en cualquiera de los dos creaba una
importacion circular entre ``views`` y ``middleware``.

Recordatorio: esto es mitigacion de ruido, no seguridad. Un bloqueo por IP
solo estorba a un escaner automatico; a cambio, cada minuto de mas es un
usuario legitimo que puede quedarse fuera. De ahi el techo.
"""

from datetime import timedelta

from django.utils import timezone

#: Techo absoluto de un bloqueo. Sin el, cada peticion sumaba otro intervalo
#: y un bot insistente lo volvia perpetuo -- y un falso positivo, tambien.
MAX_BLOCK = timedelta(hours=24)

#: Cuantas rutas se conservan. Son para diagnosticar; con las ultimas basta, y
#: sin tope un bot podia inflar el JSON de la fila hasta pesar megabytes.
MAX_STORED_PATHS = 50


def capped_until(extra, *, current=None):
    """
    Hasta cuando queda bloqueada la IP, sin pasarse del techo.

    Parameters:
        extra (timedelta): cuanto se quiere alargar desde ahora.
        current (datetime | None): hasta cuando estaba bloqueada ya.

    Returns:
        datetime: el nuevo ``blocked_until``, nunca mas alla de ``MAX_BLOCK``.
    """
    now = timezone.now()
    base = current if (current and current > now) else now

    return min(base + extra, now + MAX_BLOCK)


def note_attempt(info: dict, request) -> dict:
    """
    Anota un intento en el ``session_info`` de un bloqueo.

    Devuelve el diccionario actualizado, con la lista de rutas ya recortada.
    """
    info = dict(info or {})

    info['attempt_count'] = int(info.get('attempt_count', 0)) + 1

    paths = list(info.get('paths') or [])
    paths.append(request.path)
    info['paths'] = paths[-MAX_STORED_PATHS:]

    info['timestamp'] = timezone.now().isoformat()
    info['user_agent'] = request.META.get('HTTP_USER_AGENT')
    info['referer'] = request.META.get('HTTP_REFERER')

    return info
