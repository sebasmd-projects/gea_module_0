# apps/common/utils/scanning.py
"""
La segunda señal: quien enumera rutas que no existen.

La trampa anti-escaneo (``attack_patterns.py``) sólo salta con los términos de
``COMMON_ATTACK_TERMS``. Eso la hace precisa --y por eso puede permitirse
bloquear al primer intento-- pero también la deja ciega ante todo lo que no
esté escrito en la lista: rutas de un CMS que nadie anticipó, un diccionario
de nombres de copia de seguridad, `/api/v1/...` a ver qué contesta. Ampliar la
lista no es la respuesta: cada término nuevo es una ruta legítima menos
disponible, y ya hubo un autobloqueo por meter `env`.

Lo que sí distingue a un escáner sin depender de acertar el nombre es el
**patrón de la actividad**: pedir muchas rutas distintas que no existen, en
poco tiempo. Una persona que se equivoca de URL genera uno o dos 404; un
diccionario genera decenas por minuto, y casi nunca repite ruta.

De ahí las dos condiciones, que tienen que darse las dos:

1. **Volumen**: más de ``threshold`` respuestas 404 en la ventana.
2. **Dispersión**: sobre rutas mayormente distintas. Recargar veinte veces un
   enlace roto de un correo es un usuario molesto, no un escaneo, y esa
   asimetría es la que evita el falso positivo más probable.

Falla **abierto**, y aquí sí
----------------------------
Esto decide un bloqueo, no un permiso. Con la cache caída, fallar cerrado
significaría empezar a bloquear a cualquiera que reciba un 404 --incluidos los
usuarios legítimos-- por una avería que no es suya. El coste de fallar abierto
es que durante el corte no se detecta enumeración, que es exactamente la
situación de antes de que esto existiera. Es la asimetría que
``throttling.py`` describe: lo que impide este límite es una molestia que se
acaba cuando se acaba el corte.
"""

import logging

from django.conf import settings
from django.core.cache import cache

from .client_ip import get_client_ip

logger = logging.getLogger(__name__)

#: Cuántos 404 en la ventana antes de mirar si es enumeración. Generoso a
#: propósito: los falsos positivos aquí dejan fuera a gente de verdad, y el
#: coste de un escáner que tarda un minuto más en frenarse es cero.
DEFAULT_THRESHOLD = 20

#: La ventana, en segundos. Cinco minutos: lo bastante corta para que un
#: navegar torpe a lo largo de una tarde no acumule, y lo bastante larga para
#: que un escáner lento no la esquive espaciando las peticiones.
DEFAULT_WINDOW = 300

#: Cuántas rutas distintas se recuerdan por IP. Es el tope del conjunto que se
#: guarda en cache; sin él, un escáner con rutas aleatorias infla la entrada.
MAX_TRACKED_PATHS = 60

#: Qué proporción de las rutas tiene que ser distinta para llamarlo
#: enumeración. 0.5 quiere decir: la mitad de los 404 fueron a sitios
#: distintos. Recargar la misma URL rota no llega ni de lejos.
DISTINCT_RATIO = 0.5


def _setting(name, default):
    return getattr(settings, name, default)


def threshold() -> int:
    return int(_setting('SCAN_404_THRESHOLD', DEFAULT_THRESHOLD))


def window() -> int:
    return int(_setting('SCAN_404_WINDOW_SECONDS', DEFAULT_WINDOW))


def _key(client_ip: str) -> str:
    return f'scan404:{client_ip}'


def note_not_found(request, path: str) -> dict:
    """
    Apunta un 404 de esta IP y devuelve el estado de su ventana.

    Returns:
        dict: ``count`` (404 en la ventana), ``distinct`` (rutas distintas
        recordadas) y ``degraded`` (True si la cache no contestó, en cuyo caso
        los dos números no valen y quien llama no debe decidir nada).
    """
    client_ip = get_client_ip(request)

    if not client_ip:
        return {'count': 0, 'distinct': 0, 'degraded': True}

    key = _key(client_ip)

    try:
        state = cache.get(key)
    except Exception:  # noqa: BLE001
        state = None

    # `None` aquí es ambiguo a propósito y hay que tratarlo como tal: puede ser
    # la primera vez de esta IP, o puede ser Redis caído devolviendo None en
    # vez de lanzar (ver el encabezado de throttling.py). Se distingue por lo
    # que devuelve el `set` de abajo, no por esto.
    state = state if isinstance(state, dict) else {'count': 0, 'paths': []}

    state['count'] = int(state.get('count', 0)) + 1

    paths = list(state.get('paths') or [])

    if path not in paths:
        paths.append(path)

    state['paths'] = paths[-MAX_TRACKED_PATHS:]

    try:
        cache.set(key, state, timeout=window())
        stored = cache.get(key)
    except Exception:  # noqa: BLE001
        stored = None

    if not isinstance(stored, dict):
        # Ni se guardó ni se pudo releer: la cache no está. No se decide nada.
        return {'count': 0, 'distinct': 0, 'degraded': True}

    return {
        'count': int(stored.get('count', 0)),
        'distinct': len(stored.get('paths') or []),
        'degraded': False,
    }


def looks_like_enumeration(state: dict) -> bool:
    """
    Si el estado de la ventana parece un diccionario y no un despiste.

    Las dos condiciones tienen que darse a la vez. El volumen solo no basta
    --veinte recargas de un enlace roto son veinte 404-- y la dispersión sola
    tampoco --cinco rutas distintas mal escritas en una tarde son un usuario
    perdido, no un escáner.
    """
    if state.get('degraded'):
        return False

    count = state.get('count', 0)

    if count < threshold():
        return False

    return state.get('distinct', 0) >= max(2, int(count * DISTINCT_RATIO))


def forget(request) -> None:
    """
    Olvida la ventana de esta IP.

    Se llama al bloquear: a partir de ahí la cuenta la lleva el propio bloqueo
    y dejar la ventana llena haría que, al expirar el bloqueo, el siguiente
    404 disparara otro inmediatamente.
    """
    client_ip = get_client_ip(request)

    if not client_ip:
        return

    try:
        cache.delete(_key(client_ip))
    except Exception:  # noqa: BLE001
        logger.debug('scanning: no se pudo limpiar la ventana de %s', client_ip)
