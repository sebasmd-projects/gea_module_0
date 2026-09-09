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


# ==========================================================
# De un `session_info` a las columnas de la fila
# ==========================================================

def apply_to_entry(entry, info: dict, request=None, *, pattern=None) -> None:
    """
    Vuelca en las columnas de la fila lo que dice su ``session_info``.

    Existe para que las columnas se deriven **en un solo sitio**. Son datos
    duplicados a propósito --el JSON sigue teniendo el rastro entero-- y esa
    clase de duplicación sólo se sostiene si hay una única función que la
    escribe. Con dos, la tabla acabaría diciendo cuatro intentos donde el JSON
    dice nueve, y a partir de ahí no se puede creer ninguno de los dos.

    No guarda: quien llama decide cuándo, dentro de su propia transacción.

    Parameters:
        entry: la instancia de ``IPBlockedModel``.
        info: su ``session_info`` ya actualizado.
        request: la petición, si se tiene; de ella sale el user-agent.
        pattern: qué disparó el bloqueo, si quien llama lo sabe.
    """
    from apps.common.utils import netintel

    info = info or {}
    now = timezone.now()

    entry.attempt_count = int(info.get('attempt_count', 0))

    # Rutas **distintas**, no total de intentos. Es lo que separa a quien
    # recarga diez veces la misma URL mal escrita de quien recorre un
    # diccionario: la primera es una persona, la segunda no.
    entry.unique_paths = len(set(info.get('paths') or []))

    entry.first_seen = entry.first_seen or entry.created or now
    entry.last_seen = now

    agent = (
        (request.META.get('HTTP_USER_AGENT') if request else None)
        or info.get('user_agent')
        or ''
    )
    entry.user_agent = agent[:500]

    if pattern:
        entry.matched_pattern = str(pattern)[:150]

    # La red sólo se mira una vez: no cambia entre intentos, y la tabla de
    # prefijos se recorre entera en cada consulta.
    if not entry.network_owner and not entry.country:
        intel = netintel.describe(entry.current_ip)

        entry.network_owner = (intel['network_owner'] or '')[:100]
        entry.is_datacenter = intel['is_datacenter']
        entry.country = (intel['country'] or '')[:2]


#: Los campos que toca `apply_to_entry`, para pasarlos a `update_fields` y no
#: reescribir la fila entera --ni pisar un cambio hecho a mano desde el admin
#: mientras la petición estaba en curso.
DERIVED_FIELDS = (
    'attempt_count', 'unique_paths', 'first_seen', 'last_seen',
    'user_agent', 'matched_pattern', 'network_owner', 'is_datacenter',
    'country',
)


# ==========================================================
# Decir una duracion en voz alta
# ==========================================================

#: Las unidades, de mayor a menor, con los segundos que vale cada una. Los
#: años y los meses son los del calendario medio (365.2425 días), porque aquí
#: sirven para leer «2 meses» de un vistazo, no para calcular un vencimiento.
_UNITS = (
    ('year', 'years', 'año', 'años', 31556952),
    ('month', 'months', 'mes', 'meses', 2629746),
    ('day', 'days', 'día', 'días', 86400),
    ('hour', 'hours', 'hora', 'horas', 3600),
    ('minute', 'minutes', 'minuto', 'minutos', 60),
    ('second', 'seconds', 'segundo', 'segundos', 1),
)


def describe_duration(delta, *, parts: int = 3, spanish=None) -> str:
    """
    Una duración en años, meses, días, horas, minutos y segundos.

    Se escribe a mano en vez de usar ``timesince`` de Django por dos motivos
    concretos: ``timesince`` corta en dos unidades y nunca baja de los
    minutos, así que un bloqueo de cuarenta segundos salía como «0 minutos».
    Y un bloqueo que acaba de expirar tiene que poder decirse en segundos,
    que es justo cuando alguien está mirando la tabla.

    Parameters:
        delta: un ``timedelta``. Negativo o cero devuelve «0 segundos».
        parts: cuántas unidades como mucho. Tres es lo que se lee de un
            vistazo: «1 día 4 horas 12 minutos».
        spanish: en qué idioma. Por defecto, el que esté activo en la
            petición. La tabla vive aquí y no en un `.po` porque son doce
            palabras y hacerlas depender de un `compilemessages` sería que la
            duración de un bloqueo saliera en inglés a medio despliegue.

    Returns:
        str: la duración escrita.
    """
    if spanish is None:
        from django.utils.translation import get_language

        spanish = not (get_language() or 'es').startswith('en')

    total = int(delta.total_seconds()) if delta else 0

    if total <= 0:
        return '0 segundos' if spanish else '0 seconds'

    pieces = []

    for singular_en, plural_en, singular_es, plural_es, size in _UNITS:
        if len(pieces) >= parts:
            break

        amount, total = divmod(total, size)

        if not amount:
            continue

        if spanish:
            label = singular_es if amount == 1 else plural_es
        else:
            label = singular_en if amount == 1 else plural_en

        pieces.append(f'{amount} {label}')

    return ' '.join(pieces)
