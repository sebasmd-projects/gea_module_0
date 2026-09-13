# apps/common/utils/outbound.py
"""
Comprobar que una URL de configuración es lo que se espera antes de abrirla.

(El nombre obvio para esto sería ``urls.py``, y está cogido: en una app de
Django ese fichero es el URLconf. De ahí ``outbound``, que además dice lo que
hace — esto va sobre las llamadas que **salen**, no sobre las que entran.)

``urllib.request.urlopen`` no abre sólo HTTP. Abre además ``file://``,
``ftp://`` y lo que tengan registrado los manejadores instalados. Es una
propiedad de la biblioteca, no un descuido de quien la llama, y por eso no se
arregla mirando el código con más cuidado: se arregla comprobando el esquema
antes de pasárselo.

Aquí importa porque dos sitios abren una URL que sale de la **configuración**,
no de una petición: el calentamiento que corre por cron cada tres minutos
(``GEA_WARMUP_URL``) y la comprobación de salud. Una variable de entorno mal
puesta --o cambiada por quien pueda tocar el entorno del cron-- convertiría
cualquiera de las dos en una lectura de ficheros locales, en bucle y sin que
nadie lo note, porque el resultado de esas llamadas se tira.

No es control de acceso ni sustituye a nada: es cerrar la puerta que la
biblioteca deja abierta por defecto.
"""

from urllib.parse import urlsplit

#: Lo único que tiene sentido abrir desde aquí.
ALLOWED_SCHEMES = frozenset({'http', 'https'})


class InsecureUrlScheme(ValueError):
    """La URL no es http(s), así que no se abre."""


def is_http_url(url: str) -> bool:
    """
    Si la URL se puede abrir: http(s) y con servidor.

    La versión que no levanta nada, para quien sólo quiere decidir. La tarea
    de calentamiento la usa así: ahí una URL mal configurada no es una
    excepción que haya que atrapar, es una rama --se registra y se vuelve--, y
    escribirla con ``try/except`` haría que el log llevara cada tres minutos la
    traza de un error que nos hemos levantado nosotros mismos.
    """
    try:
        require_http_url(url)
    except InsecureUrlScheme:
        return False

    return True


def require_http_url(url: str) -> str:
    """
    Devuelve la URL si es http(s); si no, levanta ``InsecureUrlScheme``.

    Devuelve la propia URL para poder encadenar
    (``urlopen(require_http_url(url))``) sin escribirla dos veces.

    Raises:
        InsecureUrlScheme: si el esquema no es http ni https, o si no hay
            servidor --``http:///etc/passwd`` tiene el esquema bueno y no
            apunta a ninguna parte.
    """
    parts = urlsplit(url or '')

    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise InsecureUrlScheme(
            f'solo se abren URLs http o https, y esta es '
            f'{parts.scheme or "sin esquema"!r}: {url!r}'
        )

    if not parts.netloc:
        raise InsecureUrlScheme(f'la URL no tiene servidor: {url!r}')

    return url
