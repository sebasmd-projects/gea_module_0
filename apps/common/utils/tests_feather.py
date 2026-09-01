# apps/common/utils/tests_feather.py
"""
Que ninguna pagina se quede sin la libreria de iconos.

    Uncaught ReferenceError: feather is not defined
        at scripts.js:3

``scripts.js`` se carga desde ``raw.html``, o sea en **todas** las paginas, y
su primera linea llama a ``feather.replace()``. La libreria, en cambio, estaba
declarada a mano en diecinueve plantillas sueltas: en cualquier pagina que no
fuera una de esas diecinueve --la portada, la verificacion de certificados,
las paginas AEGIS-- la llamada reventaba.

Y no se quedaba en un mensaje de consola. La excepcion salta **dentro** del
manejador de ``DOMContentLoaded``, asi que aborta el resto: en esas paginas no
se inicializaban los tooltips ni los popovers, no se resaltaba el enlace
activo, y --lo que se nota-- el boton de plegar el menu lateral no hacia nada.

Se arreglo por los dos lados, y las dos mitades se prueban aqui:

1. La libreria se carga **una vez** en ``raw.html``, antes de ``scripts.js``.
2. La llamada va guardada, porque una libreria de adorno no puede llevarse por
   delante la navegacion aunque el CDN falle.

    manage.py test apps.common.utils.tests_feather \\
        --settings=app_core.settings_test
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

FEATHER = 'feather-icons'
SCRIPTS = 'js/scripts.js'


class TestEveryPageGetsTheLibrary(TestCase):
    """
    Paginas publicas que **no** cargaban feather y si cargaban scripts.js.

    Son las que reportaban el error. Se piden de verdad y se mira el HTML: es
    la unica forma de comprobar el orden real de las etiquetas, que es lo que
    decide si la libreria esta definida cuando corre el script.
    """

    # `core:privacy` y `core:terms` no estan aqui a proposito: sus plantillas
    # son ficheros de cero bytes, asi que no pintan nada -- ni cabecera, ni
    # scripts, ni contenido. No pueden fallar por feather porque no cargan
    # feather ni nada. Es un hallazgo aparte, y de contenido: el texto legal
    # lo tiene que escribir el despacho, no una prueba.
    PUBLIC_PAGES = (
        'core:index',
        'certificates:certificates_landing',
        'certificates:input_document_verification_aegis',
        'certificates:input_employee_verification_ipcon',
    )

    def test_they_all_load_feather(self):
        for name in self.PUBLIC_PAGES:
            with self.subTest(page=name):
                body = self.client.get(reverse(name)).content.decode()

                self.assertIn(FEATHER, body)

    def test_feather_comes_before_the_script_that_uses_it(self):
        """
        El orden importa: ``scripts.js`` no es `defer`, asi que si la libreria
        fuera despues, en el momento de ejecutarse no estaria definida.
        """
        for name in self.PUBLIC_PAGES:
            with self.subTest(page=name):
                body = self.client.get(reverse(name)).content.decode()

                self.assertLess(
                    body.index(FEATHER), body.index(SCRIPTS),
                    'feather has to be declared before scripts.js',
                )

    def test_it_is_declared_only_once_per_page(self):
        """
        Estaba en diecinueve plantillas. Una pagina del panel llegaba a
        declararlo dos veces --la suya y la del layout-- y con eso ninguna de
        las dos era la fuente de verdad al cambiar de version.
        """
        for name in self.PUBLIC_PAGES:
            with self.subTest(page=name):
                body = self.client.get(reverse(name)).content.decode()

                self.assertEqual(body.count('feather.min.js'), 1)


class TestTheTemplatesDoNotDeclareItAgain(SimpleTestCase):
    """
    La regla, comprobada sobre los ficheros: ``raw.html`` y nadie mas.

    Sin esto, la primera plantilla nueva que copie el bloque de iconos de otra
    --que es como llegaron a ser diecinueve-- lo vuelve a duplicar.
    """

    def templates_with_feather(self):
        """
        Busca en ``templates/`` **y** dentro de las apps.

        Las dos, porque la primera pasada solo miro la carpeta de arriba y
        `core/index.html` --que vive en `apps/common/core/templates/`-- se
        quedo con su copia. Una prueba que solo mira medio arbol da una
        confianza que no corresponde.
        """
        base = Path(settings.BASE_DIR)
        roots = [base / 'templates', base / 'apps']

        found = []

        for root in roots:
            for path in root.rglob('*.html'):
                try:
                    body = path.read_text(encoding='utf-8')
                except (UnicodeDecodeError, OSError):
                    continue

                if 'feather.min.js' in body:
                    found.append(path)

        return sorted(found)

    def test_only_the_base_template_loads_it(self):
        found = [
            str(path.relative_to(Path(settings.BASE_DIR)))
            for path in self.templates_with_feather()
        ]

        self.assertEqual(found, ['templates/raw.html'])


class TestTheCallIsGuarded(SimpleTestCase):
    """
    Cinturon y tirantes. Aunque el CDN falle o se caiga, el resto del script
    tiene que seguir corriendo: los iconos son decoracion, el menu no.
    """

    def script(self) -> str:
        path = (
            Path(settings.BASE_DIR) / 'public' / 'staticfiles' / 'js' /
            'scripts.js'
        )

        return path.read_text(encoding='utf-8')

    def test_it_checks_before_calling(self):
        body = self.script()

        self.assertIn("typeof feather !== 'undefined'", body)

    def test_there_is_no_unguarded_call_left(self):
        """
        Que no quede ninguna llamada suelta fuera del `if`, que seria
        exactamente el mismo fallo en otra linea.
        """
        body = self.script()

        calls = [
            line.strip() for line in body.splitlines()
            if 'feather.replace()' in line
        ]

        self.assertEqual(len(calls), 1)

        guard = body.index("typeof feather !== 'undefined'")
        call = body.index('feather.replace()')

        self.assertLess(guard, call)

    def test_the_rest_of_the_handler_is_still_there(self):
        """
        Lo que se perdia cuando la excepcion abortaba el manejador.
        """
        body = self.script()

        for piece in ('sidebarToggle', 'Tooltip', 'Popover',
                      'layoutSidenav_content'):
            with self.subTest(piece=piece):
                self.assertIn(piece, body)

    def test_nothing_runs_before_the_guard(self):
        """
        La llamada era la primera linea del manejador, y por eso se perdia
        todo. Si algo tuviera que ejecutarse antes, tendria que ir por delante
        de la comprobacion, no depender de que no falle.
        """
        body = self.script()

        before = body[:body.index('feather.replace()')]

        self.assertNotIn('addEventListener(\'click\'', before)
