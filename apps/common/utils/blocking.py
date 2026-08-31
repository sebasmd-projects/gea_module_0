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

Por que la duracion es exponencial
----------------------------------
Habia dos politicas distintas para lo mismo. La vista trampa multiplicaba
(``base * intentos``) y el middleware sumaba un intervalo fijo, asi que la
duracion de un bloqueo dependia de por donde hubiera entrado la peticion.

Las dos crecian ademas demasiado despacio para lo que hace un escaner. Un bot
tira cientos de rutas por minuto: multiplicar por el numero de intentos le
sale barato al principio, que es cuando conviene que le salga caro. Y crecer
por *acumulacion* -- sumar otro intervalo en cada peticion -- tiene el defecto
contrario: quien insiste mucho llega al techo aunque cada intento por separado
fuera inocuo, y ahi el que paga es el falso positivo.

Ahora hay una sola funcion, ``block_duration()``, y la duracion se deriva del
**numero de intentos**, no de cuanto llevaba bloqueado: duplicar en cada
intento pasa de minutos a horas en seis o siete peticiones -- un humano que se
equivoca de URL no llega, un escaner llega en segundos -- y como es una
funcion del contador, no se acumula sola por el mero hecho de reintentar.
"""

from datetime import timedelta

from django.utils import timezone

#: Techo absoluto de un bloqueo. Sin el, cada peticion sumaba otro intervalo
#: y un bot insistente lo volvia perpetuo -- y un falso positivo, tambien.
MAX_BLOCK = timedelta(hours=24)

#: Cuantas rutas se conservan. Son para diagnosticar; con las ultimas basta, y
#: sin tope un bot podia inflar el JSON de la fila hasta pesar megabytes.
MAX_STORED_PATHS = 50

#: Tope del exponente. No cambia el resultado -- con el techo de 24 h la curva
#: se satura mucho antes -- pero evita calcular ``2 ** 40000`` para un bot que
#: lleva cuarenta mil intentos, que es tiempo de CPU regalado al que ataca.
MAX_DOUBLINGS = 16


def block_duration(attempt_count: int, base: timedelta) -> timedelta:
    """
    Cuanto dura el bloqueo tras ``attempt_count`` intentos.

    Duplica en cada intento a partir del primero y nunca pasa de
    ``MAX_BLOCK``. Con la base por defecto de 15 minutos::

        1 -> 15 min      4 ->  2 h       7 -> 16 h
        2 -> 30 min      5 ->  4 h       8 -> 24 h (techo)
        3 ->  1 h        6 ->  8 h       9+-> 24 h

    Parameters:
        attempt_count (int): intentos anotados, empezando en 1.
        base (timedelta): duracion del primer bloqueo.

    Returns:
        timedelta: la duracion, acotada a ``MAX_BLOCK``.
    """
    doublings = max(0, int(attempt_count) - 1)
    doublings = min(doublings, MAX_DOUBLINGS)

    return min(base * (2 ** doublings), MAX_BLOCK)


def block_until(attempt_count: int, base: timedelta, *, current=None):
    """
    Hasta cuando queda bloqueada la IP tras anotar un intento.

    La duracion sale del contador de intentos, no de lo que quedara del
    bloqueo anterior: reintentar no alarga por si solo. Lo unico que se
    respeta del bloqueo previo es que **no se acorta** -- bajar la duracion a
    mitad de un bloqueo seria premiar la insistencia.

    Parameters:
        attempt_count (int): intentos anotados, empezando en 1.
        base (timedelta): duracion del primer bloqueo.
        current (datetime | None): hasta cuando estaba bloqueada ya.

    Returns:
        datetime: el nuevo ``blocked_until``, nunca mas alla de ``MAX_BLOCK``.
    """
    now = timezone.now()
    ceiling = now + MAX_BLOCK

    proposed = now + block_duration(attempt_count, base)

    if current and current > proposed:
        proposed = current

    return min(proposed, ceiling)


def capped_until(extra, *, current=None):
    """
    Hasta cuando queda bloqueada la IP, sin pasarse del techo.

    Se conserva para los sitios que alargan un bloqueo por una razon que no es
    el contador de intentos. Para la trampa anti-escaneo usa ``block_until()``.

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
