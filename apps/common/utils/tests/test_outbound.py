# apps/common/utils/tests/test_outbound.py
"""
Que `urlopen` no acabe leyendo ficheros locales porque una variable este mal.

`urllib.request.urlopen` no abre solo HTTP: abre `file://`, `ftp://` y lo que
tengan registrado los manejadores instalados. Es una propiedad de la
biblioteca, no un descuido de quien la llama.

Aqui importa en dos sitios, y los dos abren una URL que sale de la
**configuracion**: el calentamiento que corre por cron cada tres minutos
(`GEA_WARMUP_URL`) y la comprobacion de salud. Una variable mal puesta --o
cambiada por quien pueda tocar el entorno del cron-- convertiria cualquiera de
las dos en una lectura de ficheros locales en bucle, y sin que nadie lo note,
porque el resultado de esas llamadas se tira.

    manage.py test apps.common.utils.tests.test_outbound \\
        --settings=app_core.settings_test
"""

from unittest import mock

from django.test import SimpleTestCase

from .. import cron
from ..outbound import ALLOWED_SCHEMES, InsecureUrlScheme, require_http_url


class WhatGetsThroughTests(SimpleTestCase):

    def test_http_and_https_pass(self):
        for url in ('http://ejemplo.test/health/',
                    'https://ejemplo.test/health/'):
            self.assertEqual(require_http_url(url), url)

    def test_the_scheme_is_read_case_insensitively(self):
        """`HTTPS://` es https. Rechazarlo seria un fallo, no una defensa."""
        self.assertTrue(require_http_url('HTTPS://ejemplo.test/'))

    def test_only_two_schemes_are_allowed(self):
        self.assertEqual(ALLOWED_SCHEMES, {'http', 'https'})


class WhatGetsRejectedTests(SimpleTestCase):

    def test_a_local_file_is_refused(self):
        with self.assertRaises(InsecureUrlScheme):
            require_http_url('file:///etc/passwd')

    def test_other_schemes_are_refused(self):
        for url in ('ftp://ejemplo.test/x', 'gopher://ejemplo.test/',
                    'data:text/plain,hola'):
            with self.assertRaises(InsecureUrlScheme):
                require_http_url(url)

    def test_a_bare_path_is_refused(self):
        """Sin esquema, `urlopen` lo trataria como un fichero local."""
        with self.assertRaises(InsecureUrlScheme):
            require_http_url('/etc/passwd')

    def test_nothing_at_all_is_refused(self):
        for url in ('', None):
            with self.assertRaises(InsecureUrlScheme):
                require_http_url(url)

    def test_the_right_scheme_pointing_nowhere_is_refused(self):
        """
        `http:///etc/passwd` lleva el esquema bueno y no tiene servidor. Sin
        comprobar el `netloc`, la comprobacion del esquema sola lo dejaria
        pasar.
        """
        with self.assertRaises(InsecureUrlScheme):
            require_http_url('http:///etc/passwd')

    def test_the_message_says_which_url_and_which_scheme(self):
        """Un aviso que no dice cual era la URL no sirve para arreglarla."""
        with self.assertRaises(InsecureUrlScheme) as caught:
            require_http_url('file:///etc/passwd')

        self.assertIn('file', str(caught.exception))
        self.assertIn('/etc/passwd', str(caught.exception))


class TheWarmupCronTests(SimpleTestCase):
    """
    El caso real: la tarea que corre cada tres minutos sin nadie mirando.
    """

    def test_a_file_url_never_reaches_urlopen(self):
        with mock.patch.dict('os.environ',
                             {'GEA_WARMUP_URL': 'file:///etc/passwd'}), \
                mock.patch.object(cron, 'urlopen') as opened:
            cron.warm_gea_app()

        opened.assert_not_called()

    def test_a_normal_url_still_works(self):
        """
        Lo otro que hay que comprobar: que la defensa no rompa el caso bueno.
        """
        with mock.patch.dict('os.environ',
                             {'GEA_WARMUP_URL': 'https://ejemplo.test/health/'}), \
                mock.patch.object(cron, 'urlopen') as opened:
            cron.warm_gea_app()

        opened.assert_called_once()
        self.assertEqual(
            opened.call_args[0][0], 'https://ejemplo.test/health/')

    def test_a_bad_url_is_logged_and_does_not_raise(self):
        """
        Una tarea de cron que levanta una excepcion llena el log de trazas y
        no arregla nada. Se registra el motivo y se sale.
        """
        with mock.patch.dict('os.environ',
                             {'GEA_WARMUP_URL': 'file:///etc/passwd'}), \
                mock.patch.object(cron, 'urlopen'), \
                mock.patch.object(cron.logger, 'error') as logged:
            cron.warm_gea_app()

        logged.assert_called_once()
