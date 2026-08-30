# apps/common/utils/axes_hooks.py
"""
Enganches de ``django-axes``, para que el bloqueo de login no sea un autobloqueo.

``axes`` estaba instalado sin una sola linea de configuracion, y sus valores
por defecto son deliberadamente severos: tres intentos fallidos y bloqueo
**permanente** (``AXES_COOLOFF_TIME = None``) **por IP** y solo por IP. En una
plataforma cuyo personal comparte la salida a internet de una oficina, eso
significa que una persona tecleando mal su contrasena tres veces deja fuera a
todo el mundo, y hasta que alguien entre a la base de datos a mano. Y como
``AXES_RESET_ON_SUCCESS`` tambien viene en ``False``, los fallos no se olvidan
nunca: se acumulan a lo largo de meses hasta que la cuenta atras se agota sola.

Aqui viven las dos piezas que ``settings.py`` necesita para arreglarlo sin
duplicar logica que ya existe en el proyecto:

1. **Una sola respuesta a "de donde viene esta peticion".** ``axes`` trae su
   propia deteccion de IP; el proyecto ya tiene la suya en ``client_ip``, que
   por defecto no se cree ``X-Forwarded-For`` y solo lo usa si hay proxies
   propios declarados en ``TRUSTED_PROXY_DEPTH``. Hoy los dos coinciden por
   casualidad, porque ninguno se cree la cabecera; el dia que se declare un
   proxy dejarian de coincidir y el bloqueo de login caeria sobre una IP
   distinta de la que ve el resto de la aplicacion. Se enchufa la del proyecto
   y se acaba la ambiguedad.

2. **Que la lista blanca sirva para el login.** ``WhiteListedIPModel`` es el
   remedio documentado cuando alguien queda bloqueado por error, pero ``axes``
   no la conoce: anadir la IP desbloqueaba la mitigacion anti-escaneo y dejaba
   el login igual de cerrado. Es exactamente el mismo agujero que ya se cerro
   entre la vista que bloquea y el middleware que aplica el bloqueo.

Nada de esto convierte el bloqueo por IP en un control de seguridad: sigue
siendo un freno a la fuerza bruta, y ante la duda vale mas dejar entrar a un
atacante lento que dejar fuera al equipo.

Hay ademas una tercera pieza, y sin ella las otras dos no sirven de nada:
``axes`` no se enteraba de **quien** fallaba. Busca el usuario en un campo
``username`` del POST, pero el login de ``django-two-factor-auth`` es un
wizard de ``formtools`` y su campo se llama ``auth-username``. Resultado:
todos los intentos fallidos se guardaban con ``username = None``. Eso tiene
dos consecuencias que se ven en las pruebas:

* Configurar el bloqueo por la pareja (IP, usuario) **degrada en silencio** a
  bloqueo por IP, porque el usuario siempre es el mismo: nadie. La oficina
  entera se sigue quedando fuera.
* Y al reves: quien luego llega con la contrasena correcta se consulta como
  la pareja (IP, "ana"), que no tiene ni un fallo registrado, asi que **entra
  pese al bloqueo**.

Por eso ``username()`` mira primero las credenciales y despues los dos nombres
de campo que usa el proyecto.
"""

import logging

from .client_ip import get_client_ip, is_whitelisted

logger = logging.getLogger(__name__)

# El login vive en un wizard de formtools, que prefija sus campos con el paso.
USERNAME_FIELDS = ('auth-username', 'username')


def client_ip(request) -> str:
    """
    IP para ``AXES_CLIENT_IP_CALLABLE``.

    Adaptador de una linea: ``axes`` pide un invocable que reciba la peticion,
    y la respuesta del proyecto ya esta escrita.
    """
    return get_client_ip(request)


def is_lockout_exempt(request, credentials=None) -> bool:
    """
    Si esta peticion de login nunca debe quedar bloqueada.

    Solo mira la lista blanca de IP. No se exime al personal interno como hace
    ``client_ip.is_exempt``, porque en el login todavia no hay sesion: quien
    intenta entrar es siempre anonimo, y eximir por ``is_staff`` aqui no
    significaria nada.

    Args:
        request: la peticion de login.
        credentials: lo que ``axes`` recogio del formulario. No se usa; la
            firma la fija ``AXES_WHITELIST_CALLABLE``.

    Returns:
        bool: True si la IP esta en la lista blanca.
    """
    try:
        return is_whitelisted(client_ip(request))
    except Exception:  # noqa: BLE001
        # La lista blanca es un remedio de disponibilidad. Si falla al
        # consultarla, lo correcto no es eximir a todo el mundo del bloqueo
        # de fuerza bruta: se sigue el camino normal.
        logger.warning('Axes whitelist check failed; falling back to lockout')
        return False


def username(request, credentials=None) -> str:
    """
    Quien esta intentando entrar, para ``AXES_USERNAME_CALLABLE``.

    ``axes`` mira por su cuenta un campo ``username`` del POST y no lo
    encuentra: el login es un wizard y su campo se llama ``auth-username``.
    Sin este invocable, cada intento fallido se guarda con ``username = None``
    y el bloqueo por pareja (IP, usuario) se queda en bloqueo por IP.

    Args:
        request: la peticion de login.
        credentials: lo que el backend paso a ``authenticate()``. Es la fuente
            preferente porque ya viene limpia.

    Returns:
        str: el nombre de usuario en minusculas y sin espacios, o '' si no se
        pudo determinar. Se normaliza para que 'Ana' y ' ana ' cuenten como el
        mismo intento y no den tres cuentas atras distintas.
    """
    value = ''

    if credentials:
        value = credentials.get('username') or ''

    if not value and request is not None:
        post = getattr(request, 'POST', None)

        if post is not None:
            for field in USERNAME_FIELDS:
                value = post.get(field) or ''

                if value:
                    break

    return value.strip().casefold()
