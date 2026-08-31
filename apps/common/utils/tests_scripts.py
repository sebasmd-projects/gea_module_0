# apps/common/utils/tests_scripts.py
"""
Que ningun script global se cargue dos veces.

Esto viene de un fallo que costo encontrar. ``summary_form.html`` volvia a
cargar ``busy_buttons.js``, que ``raw.html`` ya trae para todas las paginas. Dos
copias del modulo son dos escuchadores de ``submit`` en ``document``, y ese
modulo lleva una proteccion contra el doble clic: el primero marcaba el
formulario como «enviandose» y ponia el boton ocupado, y **el segundo veia esa
marca, lo tomaba por un doble clic y cancelaba el envio**.

El sintoma no apuntaba a ningun sitio: el boton se quedaba en «Procesando…»
para siempre, no aparecia ninguna peticion en la pestana de red, y los logs del
servidor estaban vacios --porque del lado del servidor no llegaba a pasar nada.
Se busco durante un buen rato en el servidor un fallo que estaba en una etiqueta
``<script>`` de mas.

El modulo ya no se instala dos veces aunque el fichero se cargue dos veces, asi
que el fallo esta cerrado por su lado. Esto cierra el otro: que la duplicacion
no vuelva a colarse en una plantilla sin que nadie se entere.

    manage.py test apps.common.utils.tests_scripts \\
        --settings=app_core.settings_test
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

TEMPLATES = Path(settings.BASE_DIR) / 'templates'

# Los que carga el esqueleto para todas las paginas.
GLOBAL_TEMPLATES = ('raw.html', 'partials/toasts.html')

SCRIPT = re.compile(r"""<script[^>]*\bsrc=["']?\{%\s*static\s*['"]([^'"]+)['"]""")


def scripts_in(path: Path):
    if not path.exists():
        return set()

    return set(SCRIPT.findall(path.read_text(encoding='utf-8')))


def global_scripts():
    found = set()

    for name in GLOBAL_TEMPLATES:
        found |= scripts_in(TEMPLATES / name)

    return found


class TestNoScriptIsLoadedTwice(SimpleTestCase):

    def test_the_base_layout_really_carries_some(self):
        """
        Si esto falla, el resto de la prueba no comprueba nada: querria decir
        que la expresion ya no reconoce las etiquetas y todo pasaria en vacio.
        """
        self.assertIn('js/busy_buttons.js', global_scripts())
        self.assertIn('js/toasts.js', global_scripts())

    def test_no_page_reloads_a_script_the_layout_already_brings(self):
        globals_ = global_scripts()
        offenders = []

        for path in TEMPLATES.rglob('*.html'):
            relative = str(path.relative_to(TEMPLATES))

            if relative.replace('\\', '/') in GLOBAL_TEMPLATES:
                continue

            for script in scripts_in(path) & globals_:
                offenders.append(f'{relative} vuelve a cargar {script}')

        self.assertEqual(offenders, [])


class TestTheBusyAttributeIsTheOneTheCodeReads(SimpleTestCase):
    """
    ``busy_buttons.js`` lee ``data-loading-text``. Un boton que escriba
    ``data-busy-text`` no falla: se queda con el texto generico, y nadie se
    entera de que su etiqueta no aparece nunca.
    """

    def test_no_button_uses_an_attribute_nobody_reads(self):
        offenders = [
            str(path.relative_to(TEMPLATES))
            for path in TEMPLATES.rglob('*.html')
            if 'data-busy-text' in path.read_text(encoding='utf-8')
        ]

        self.assertEqual(offenders, [])
