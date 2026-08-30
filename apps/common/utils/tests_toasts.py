# apps/common/utils/tests_toasts.py
"""
Que un aviso se vea aunque el usuario no este mirando arriba.

Los mensajes se pintaban dentro de la pagina, en una tarjeta sobre el
contenido. Quien acaba de pulsar un boton que esta al pie de un formulario
largo se queda mirando el pie, y el aviso aparecia mil pixeles mas arriba: el
usuario no veia nada y volvia a pulsar. Un toast va en ``position: fixed`` y no
depende del scroll.

Al mover el texto de HTML ya pintado a datos JSON cambia quien lo escapa, asi
que aqui se comprueba las dos cosas: que el aviso llegue, y que un mensaje con
marcado dentro siga sin poder convertirse en marcado. Un texto de mensaje puede
venir de un error del servidor o de algo que escribio el usuario.

    manage.py test apps.common.utils.tests_toasts \\
        --settings=app_core.settings_test
"""

import json
from pathlib import Path

from django.conf import settings
from django.contrib.messages import constants
from django.contrib.messages.storage.base import Message
from django.template.loader import render_to_string
from django.test import SimpleTestCase

from .templatetags.custom_filters import messages_as_data

TEMPLATES = Path(settings.BASE_DIR) / 'templates'


def rendered(messages):
    return render_to_string('partials/toasts.html', {'messages': messages})


def payload(html):
    """El JSON que se le entrega al navegador, ya extraido del <script>."""
    start = html.index('>', html.index('id="djangoMessages"')) + 1
    end = html.index('</script>', start)

    return json.loads(html[start:end])


class TestMessagesReachTheBrowser(SimpleTestCase):

    def test_level_and_text_survive_the_trip(self):
        data = messages_as_data([
            Message(constants.SUCCESS, 'Se guardo.'),
            Message(constants.ERROR, 'No se pudo guardar.'),
        ])

        self.assertEqual(data, [
            {'level': 'success', 'message': 'Se guardo.'},
            {'level': 'error', 'message': 'No se pudo guardar.'},
        ])

    def test_a_lazy_translation_is_resolved_before_serializing(self):
        """
        Un ``gettext_lazy`` no es serializable a JSON. Casi todos los mensajes
        del proyecto lo son, asi que si no se resuelve aqui, la pagina revienta
        justo cuando hay algo que decir.
        """
        from django.utils.translation import gettext_lazy as _

        data = messages_as_data([Message(constants.INFO, _('Saved.'))])

        json.dumps(data)  # que no lance es la mitad de la prueba
        self.assertIsInstance(data[0]['message'], str)

    def test_the_page_carries_the_messages_as_data(self):
        html = rendered([Message(constants.WARNING, 'Cuidado con esto.')])

        self.assertIn('id="djangoMessages"', html)
        self.assertEqual(
            payload(html),
            [{'level': 'warning', 'message': 'Cuidado con esto.'}],
        )

    def test_a_page_without_messages_carries_no_payload(self):
        html = rendered([])

        self.assertNotIn('djangoMessages', html)
        # El script sigue estando: otras partes lanzan avisos por su cuenta.
        self.assertIn('toasts.js', html)


class TestMessagesCannotBecomeMarkup(SimpleTestCase):
    """
    El texto pasa a ser un dato, y quien lo escapa cambia. Que siga escapado.
    """

    def test_markup_inside_a_message_stays_text(self):
        html = rendered([
            Message(constants.ERROR, '<script>alert(1)</script>'),
        ])

        # json_script escapa los signos de menor: el navegador no puede leer
        # ahi dentro una etiqueta que cierre el <script> que lo contiene.
        self.assertNotIn('<script>alert(1)', html)
        self.assertIn('\\u003C', html)

        # Y el texto llega entero al otro lado, sin mutilar.
        self.assertEqual(
            payload(html)[0]['message'], '<script>alert(1)</script>'
        )


class TestNoPageStillPaintsItsOwn(SimpleTestCase):
    """
    Que no quede ninguna plantilla pintando los mensajes por su cuenta.

    Si queda una, esa pagina muestra el aviso dos veces: el suyo dentro del
    contenido y el toast. Y el de dentro es justo el que no se ve.
    """

    def test_no_template_loops_over_messages_any_more(self):
        offenders = [
            str(path.relative_to(TEMPLATES))
            for path in TEMPLATES.rglob('*.html')
            if '{% for message in messages %}' in path.read_text(
                encoding='utf-8')
        ]

        self.assertEqual(offenders, [])

    def test_the_base_layout_includes_the_toasts_once(self):
        raw = (TEMPLATES / 'raw.html').read_text(encoding='utf-8')

        self.assertEqual(raw.count("include 'partials/toasts.html'"), 1)
