# apps/common/utils/tests/test_sri.py
"""
Que nada de fuera se ejecute sin comprobar que es lo que decimos que es.

Un `<script src="https://cdn...">` sin `integrity` es una promesa de que el CDN
--y cualquiera que pueda hablar por el-- va a servir siempre el mismo codigo.
La pagina de acceso carga varios de esos, y es donde se teclean la contrasena y
el codigo de un solo uso: ahi un byte cambiado no es una molestia visual.

Con `integrity` el navegador compara el hash de lo que recibe con el que esta
escrito en la etiqueta, y si no cuadra **no lo ejecuta**. Es barato y no
depende de confiar en nadie.

La asimetria que habia
----------------------
El CSS de Bootstrap si llevaba `integrity`; el **JS** de Bootstrap, no. O sea
que estaba protegido justo el recurso que no ejecuta nada. Esta prueba existe
para que esa asimetria no vuelva, sea cual sea el fichero que la reintroduzca.

Lo que no se puede firmar, y por que
------------------------------------
Dos familias, y las dos estan declaradas abajo con su motivo. No se toleran
mas: anadir un CDN nuevo sin `integrity` falla aqui, y si de verdad no se puede
firmar, la excepcion se escribe y se razona en vez de aparecer sola.

    manage.py test apps.common.utils.tests.test_sri \\
        --settings=app_core.settings_test
"""

import collections
import pathlib
import re

from django.conf import settings
from django.test import SimpleTestCase

#: Una etiqueta que carga algo por https, con lo que sea dentro.
TAG = re.compile(
    r'<(script|link)\b[^>]*?(?:src|href)="(https://[^"]+)"[^>]*?>', re.S)

#: Hosts que **no** pueden llevar `integrity`, con la razon por la que no.
#: Cada entrada es una excepcion consciente, no un olvido.
CANNOT_BE_PINNED = {
    'kit.fontawesome.com': (
        'Es un cargador mutable por diseno: la misma URL sirve contenido '
        'distinto segun la configuracion del kit, asi que no hay hash que '
        'valga. Cerrarlo de verdad es pasar a una version fija de Font '
        'Awesome, y eso toca los iconos de toda la plataforma.'
    ),
    'cdn.jotfor.ms': (
        'Formularios embebidos de JotForm (Hermes y Orion). Sus URL llevan un '
        'identificador de compilacion que ellos rotan, asi que un hash fijo '
        'rompe el formulario en su siguiente despliegue. Es la contrapartida '
        'de embeber un formulario de un tercero.'
    ),
}

#: El propio dominio. No es un tercero.
OWN_HOSTS = {'geausa.propensionesabogados.com'}


def offending_tags():
    """Etiquetas de terceros sin `integrity`, agrupadas por host."""
    found = collections.defaultdict(list)
    root = pathlib.Path(settings.BASE_DIR) / 'templates'

    for path in sorted(root.rglob('*.html')):
        content = path.read_text(encoding='utf-8')

        for match in TAG.finditer(content):
            tag, url = match.group(0), match.group(2)

            if 'integrity=' in tag:
                continue

            host = url.split('/')[2]

            if host in OWN_HOSTS or host in CANNOT_BE_PINNED:
                continue

            found[host].append(str(path.relative_to(root)))

    return found


class EveryThirdPartyAssetIsPinnedTests(SimpleTestCase):

    def test_nothing_loads_unverified(self):
        offenders = offending_tags()

        self.assertEqual(
            dict(offenders), {},
            'estos recursos de terceros se cargan sin comprobar que sean los '
            'esperados; anade integrity="sha384-..." y crossorigin, o si de '
            'verdad no se puede, declaralo en CANNOT_BE_PINNED con su motivo',
        )

    def test_the_bootstrap_bundle_is_pinned(self):
        """
        El caso concreto que dio origen a esto: el CSS lo llevaba y el JS no,
        o sea que estaba firmado justo lo que no ejecuta nada.
        """
        raw = (pathlib.Path(settings.BASE_DIR) / 'templates' / 'raw.html')
        content = raw.read_text(encoding='utf-8')

        bundle = re.search(
            r'<script[^>]*bootstrap\.bundle\.min\.js[^>]*>', content, re.S)

        self.assertIsNotNone(bundle, 'ya no se carga el bundle de Bootstrap')
        self.assertIn('integrity="sha384-', bundle.group(0))

    def test_nothing_is_loaded_from_an_unpinned_version(self):
        """
        Una URL sin version sigue a la ultima publicacion del paquete: hoy
        sirve una cosa y manana otra, sin que nadie lo decida. Y ademas no
        admite `integrity`, porque el hash cambiaria solo.

        Era el caso de `bootstrap-icons`, que se cargaba en 28 plantillas sin
        version ninguna.
        """
        root = pathlib.Path(settings.BASE_DIR) / 'templates'
        unpinned = []

        for path in sorted(root.rglob('*.html')):
            for match in TAG.finditer(path.read_text(encoding='utf-8')):
                url = match.group(2)

                if not url.startswith('https://cdn.jsdelivr.net/npm/'):
                    continue

                package = url[len('https://cdn.jsdelivr.net/npm/'):]

                if '@' not in package.split('/')[0]:
                    unpinned.append(f'{url}  ({path.relative_to(root)})')

        self.assertEqual(unpinned, [], 'sin version, la URL sigue a la ultima')


class TheExceptionsAreDeclaredTests(SimpleTestCase):
    """
    Una excepcion sin motivo escrito es un olvido con mejor aspecto.
    """

    def test_every_exception_has_a_reason(self):
        for host, reason in CANNOT_BE_PINNED.items():
            self.assertGreater(
                len(reason), 60,
                f'{host} esta exento sin explicar por que',
            )
