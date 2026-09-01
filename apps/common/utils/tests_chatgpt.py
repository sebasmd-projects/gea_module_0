# apps/common/utils/tests_chatgpt.py
"""
La traduccion automatica: que no invente y que no tumbe nada.

Es la unica integracion externa del catalogo de activos, y ocurre **dentro
del guardado** (senal ``pre_save``, sin cola de tareas). Eso la pone en el
camino critico de crear un activo o una orden, asi que lo que importa no es
que traduzca bien -- eso depende de OpenAI -- sino que no haga dano cuando no
puede traducir.

Dos fallos que salieron al escribir esto:

* **En desarrollo devolvia el codigo del idioma.** Traducir "Bono aleman" de
  es a en devolvia la cadena ``"es"``. Todo activo creado en local se quedaba
  con ``en_name = "es"``. Era un ``text`` mal escrito.
* **Sin ``CHAT_GPT_API_KEY`` no arrancaba el proyecto.** El constructor
  lanzaba ``ValueError``, y los dos sitios que usan la clase la instancian a
  nivel de modulo, con ``models.py`` importando sus senales: una integracion
  opcional sin configurar se llevaba por delante el catalogo entero.

    manage.py test apps.common.utils.tests_chatgpt \\
        --settings=app_core.settings_test
"""

from unittest import mock

from django.test import SimpleTestCase, override_settings

from .functions.chatgpt_api import ChatGPTAPI

TEXT = 'Bono aleman de 1923'


class TestItSurvivesWithoutAKey(SimpleTestCase):
    """
    Traducir es una comodidad. Que falte no puede ser peor que un campo sin
    traducir.
    """

    @override_settings(CHAT_GPT_API_KEY=None)
    def test_building_it_does_not_raise(self):
        """
        Lo que tumbaba el proyecto: `assets/models.py` importa sus senales, y
        las senales instancian esto al importarse.
        """
        translator = ChatGPTAPI()

        self.assertFalse(translator.is_available)

    @override_settings(CHAT_GPT_API_KEY='')
    def test_an_empty_key_counts_as_no_key(self):
        self.assertFalse(ChatGPTAPI().is_available)

    @override_settings(CHAT_GPT_API_KEY=None, DEBUG=False)
    def test_it_returns_the_original_text(self):
        self.assertEqual(
            ChatGPTAPI().translate(TEXT, src='es', dst='en'), TEXT)

    @override_settings(CHAT_GPT_API_KEY=None)
    def test_the_signals_module_still_imports(self):
        """
        La comprobacion de verdad: sin clave, la app tiene que cargar.
        """
        import importlib

        for name in (
            'apps.project.specific.assets_management.assets.signals',
            'apps.project.specific.assets_management.buyers.signals',
        ):
            with self.subTest(module=name):
                importlib.reload(importlib.import_module(name))


class TestItDoesNotCallOutInDevelopment(SimpleTestCase):

    @override_settings(DEBUG=True)
    def test_it_returns_the_original_text(self):
        """
        Devolvia `src`, o sea la cadena "es". Cada activo creado en local se
        quedaba con `en_name = "es"`.
        """
        result = ChatGPTAPI().translate(TEXT, src='es', dst='en')

        self.assertEqual(result, TEXT)
        self.assertNotEqual(result, 'es')

    @override_settings(DEBUG=True)
    def test_it_never_returns_a_language_code(self):
        for src, dst in (('es', 'en'), ('en', 'es')):
            with self.subTest(direction=f'{src}->{dst}'):
                result = ChatGPTAPI().translate(TEXT, src=src, dst=dst)

                self.assertNotIn(result, ('es', 'en'))

    @override_settings(DEBUG=True)
    def test_it_does_not_touch_the_network(self):
        translator = ChatGPTAPI()

        with mock.patch.object(translator, 'client') as client:
            translator.translate(TEXT, src='es', dst='en')

        client.responses.create.assert_not_called()


class TestTheEdges(SimpleTestCase):

    @override_settings(DEBUG=True)
    def test_empty_text_gives_empty_text(self):
        self.assertEqual(ChatGPTAPI().translate('', src='es', dst='en'), '')
        self.assertEqual(ChatGPTAPI().translate(None, src='es', dst='en'), '')

    @override_settings(DEBUG=True)
    def test_whitespace_is_collapsed(self):
        result = ChatGPTAPI().translate(
            '  Bono   aleman \n de 1923 ', src='es', dst='en')

        self.assertEqual(result, 'Bono aleman de 1923')

    @override_settings(DEBUG=True)
    def test_it_respects_the_character_limit(self):
        """
        Los campos tienen `max_length`. Sin recortar, una descripcion larga
        haria fallar el guardado justo despues de haber pagado la llamada.
        """
        result = ChatGPTAPI().translate(
            'x' * 500, src='es', dst='en', max_chars=50)

        self.assertEqual(len(result), 50)


class TestWhenTheApiMisbehaves(SimpleTestCase):
    """
    Ocurre dentro del `pre_save`, o sea dentro de la peticion y con
    `ATOMIC_REQUESTS`. Una excepcion que suba de aqui tumba el guardado.
    """

    def translator(self):
        with override_settings(CHAT_GPT_API_KEY='una-clave'):
            return ChatGPTAPI()

    @override_settings(DEBUG=False)
    def test_a_connection_error_does_not_propagate(self):
        from openai import APIConnectionError

        translator = self.translator()

        with mock.patch.object(
            translator, 'client',
            **{'responses.create.side_effect': APIConnectionError(
                request=mock.Mock())},
        ):
            self.assertEqual(
                translator.translate(TEXT, src='es', dst='en'), '')

    @override_settings(DEBUG=False)
    def test_an_unexpected_error_does_not_propagate_either(self):
        translator = self.translator()

        with mock.patch.object(
            translator, 'client',
            **{'responses.create.side_effect': RuntimeError('algo raro')},
        ):
            self.assertEqual(
                translator.translate(TEXT, src='es', dst='en'), '')
