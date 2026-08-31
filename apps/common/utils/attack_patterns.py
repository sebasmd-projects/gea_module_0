"""
Trampa anti-escaneo.

Esto es **mitigacion de ruido, no seguridad**: sirve para que los escaneres
automaticos de WordPress/phpMyAdmin dejen de generar 404 y consuman recursos.
Ninguna decision de seguridad real debe apoyarse aqui.

Por eso el criterio de diseno es *fallar abierto*: ante la duda, dejar pasar.
Un falso positivo aqui deja fuera a un usuario legitimo, que es mucho peor que
dejar entrar a un escaner.

El problema que tenia
---------------------
El patron era ``^.*(?:termino1|termino2|...).*$``: buscaba el termino en
**cualquier posicion** de la ruta, como subcadena suelta. Con terminos como
``env``, ``conf``, ``test``, ``index`` o ``sql`` eso convierte en trampa
cualquier ruta legitima que los contenga —``/envio/``, ``/confirmar/``,
``/contest/``— y bloquea la IP del usuario.

Lo que hace ahora
-----------------
1. El termino tiene que ser un **segmento completo** de la ruta o el nombre de
   un archivo, no una subcadena arbitraria. ``/wp-admin/`` cae; ``/envio/`` no.
2. Al arrancar se comprueba el patron contra las rutas propias del proyecto y
   se avisa por log de cualquier colision, para que un termino nuevo no tumbe
   una ruta en silencio (``manage.py check_attack_terms``).
"""

import logging
import re

from django.conf import settings
from django.urls import re_path

from .views import HttpRequestAttackView

logger = logging.getLogger(__name__)


def normalize_terms(terms) -> list:
    """Limpia la lista de terminos: sin vacios, sin duplicados, sin barras."""
    seen = []

    for term in terms or ():
        term = (term or '').strip().strip('/')

        if not term:
            continue

        if term not in seen:
            seen.append(term)

    return seen


def build_pattern(terms) -> str:
    """
    Construye el regex de la trampa.

    El termino debe ocupar un segmento completo de la ruta (entre barras) o ser
    el nombre del ultimo elemento, opcionalmente con extension. Nunca se acepta
    como subcadena dentro de una palabra mas larga: es justo lo que provocaba
    el autobloqueo.
    """
    terms = normalize_terms(terms)

    if not terms:
        # Sin terminos no hay trampa: un patron vacio matchearia todo.
        return ''

    alternation = '|'.join(re.escape(term) for term in terms)

    # (^|/) .? termino (.ext)* (/|$)
    #
    # La parte de la extension no es un adorno: sin ella la trampa dejaba
    # pasar justo lo que mas se escanea. Los terminos se escriben sin
    # extension --``xmlrpc``, ``wlwmanifest``, ``wp-login``-- pero lo que
    # llega es ``/xmlrpc.php`` y ``/wlwmanifest.xml``, y exigir barra o fin
    # justo despues del termino descartaba las dos.
    #
    # Se permiten varias (``config.php.bak``) y se acotan a letras y digitos:
    # sin acotar, ``.*`` volveria a hacer del termino una subcadena suelta y
    # con ella el autobloqueo de usuarios legitimos. Con esto ``/envio/``
    # sigue pasando, porque tras ``env`` hace falta punto, barra o fin.
    #
    # El punto opcional del principio es por los dotfiles: ``/.env``,
    # ``/.git/config``, ``/.aws/credentials``. Es de lo mas escaneado que hay
    # y se colaba por un caracter. No abre la puerta a falsos positivos
    # --sigue haciendo falta que el segmento sea el termino entero-- y este
    # proyecto no tiene ninguna ruta que empiece por punto.
    return (
        r'^.*(?:^|/)\.?(?:' + alternation +
        r')(?:\.[A-Za-z0-9]{1,10})*(?:/|$).*$'
    )


def find_conflicts(pattern: str, url_patterns=None) -> list:
    """
    Rutas propias que la trampa se comeria **de verdad**.

    Django resuelve la primera coincidencia, asi que solo quedan secuestradas
    las rutas registradas **despues** de la trampa. Las que van antes
    —``two_factor``, el admin— resuelven primero y no corren peligro. Sin esta
    distincion el chequeo daria falsos positivos y nadie lo miraria.
    """
    if not pattern:
        return []

    from django.urls import get_resolver
    from django.urls.resolvers import URLPattern, URLResolver

    compiled = re.compile(pattern)
    conflicts = []

    # Cambia a True en cuanto se recorre la trampa: a partir de ahi, todo lo
    # que matchee queda efectivamente inaccesible.
    state = {'after_trap': False}

    def walk(patterns, prefix=''):
        for entry in patterns:
            route = str(getattr(entry.pattern, '_route', '') or entry.pattern)

            if isinstance(entry, URLResolver):
                walk(entry.url_patterns, prefix + route)
                continue

            if not isinstance(entry, URLPattern):
                continue

            if getattr(entry, 'name', None) == 'attack_path':
                state['after_trap'] = True
                continue

            if not state['after_trap']:
                continue

            sample = '/' + (prefix + route)
            sample = re.sub(r'<[^>]+>', 'x', sample)

            if compiled.match(sample):
                conflicts.append({
                    'name': getattr(entry, 'name', None),
                    'path': sample,
                })

    try:
        walk(
            url_patterns
            if url_patterns is not None
            else get_resolver().url_patterns
        )
    except Exception:
        logger.exception('Could not check the attack pattern against the URLconf')

    return conflicts


pattern = build_pattern(getattr(settings, 'COMMON_ATTACK_TERMS', []))

common_attack_paths = []

if pattern:
    common_attack_paths = [
        re_path(
            pattern,
            HttpRequestAttackView.as_view(),
            name='attack_path',
        ),
    ]
else:
    logger.warning(
        'COMMON_ATTACK_TERMS is empty: the anti-scan trap is disabled.'
    )
