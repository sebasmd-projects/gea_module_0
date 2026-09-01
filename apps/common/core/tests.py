# apps/common/core/tests.py
"""
Las paginas publicas y el health check.

Sin pruebas hasta ahora, y son las unicas cuatro URL que ve alguien sin
sesion. Dos cosas que merecen fijarse:

* **El health check tiene que responder incluso cuando algo esta caido.** Es
  lo que lo hace util: si devolviera un error cuando falla el correo, quien lo
  consulta veria "no responde" y no sabria que parte. Devuelve 503 con el
  detalle de que comprobacion no paso.
* **Y no puede contar de mas.** Lo consulta la tarea de calentamiento cada
  tres minutos, sin autenticacion: es publico. Un mensaje de excepcion con la
  cadena de conexion o el host del servidor de correo estaria al alcance de
  cualquiera.

    manage.py test apps.common.core --settings=app_core.settings_test
"""

import json
from unittest import mock

from django.test import TestCase
from django.urls import reverse


class TestThePublicPages(TestCase):
    """Las tres que ve alguien sin sesion, ademas del health check."""

    def test_the_landing_renders(self):
        response = self.client.get(reverse('core:index'))

        self.assertEqual(response.status_code, 200)

    def test_the_privacy_page_renders(self):
        response = self.client.get(reverse('core:privacy'))

        self.assertEqual(response.status_code, 200)

    def test_the_terms_page_renders(self):
        response = self.client.get(reverse('core:terms'))

        self.assertEqual(response.status_code, 200)

    def test_they_do_not_need_a_session(self):
        """
        Ninguna redirige al login. Terminos y privacidad tienen que poder
        leerse **antes** de registrarse, que es cuando se aceptan.
        """
        for name in ('core:index', 'core:privacy', 'core:terms'):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))

                self.assertEqual(response.status_code, 200)


class TestTheHealthCheck(TestCase):

    def setUp(self):
        self.url = reverse('core:health_check')

    def payload(self, response):
        return json.loads(response.content.decode())

    def test_everything_up_answers_200(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.payload(response)['response'], 'OK')

    def test_it_reports_the_three_checks(self):
        body = self.payload(self.client.get(self.url))

        self.assertEqual(
            set(body['checks']), {'database', 'cache', 'email'})

    def test_it_needs_no_session(self):
        """
        Lo golpea la tarea de calentamiento cada tres minutos y lo consulta
        cualquier monitor externo. Detras de un login no serviria para eso.
        """
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_a_broken_piece_answers_503_and_says_which(self):
        """
        Lo que lo hace util: no basta con fallar, hay que decir que parte.
        """
        with mock.patch(
            'apps.common.core.views.get_connection',
            side_effect=OSError('el servidor de correo no contesta'),
        ):
            response = self.client.get(self.url)

        body = self.payload(response)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(body['response'], 'Error')
        self.assertFalse(body['checks']['email']['ok'])
        # Y las que si funcionan siguen diciendolo, que es como se acota.
        self.assertTrue(body['checks']['database']['ok'])

    def test_it_does_not_leak_the_error_message(self):
        """
        Es publico. Un mensaje de excepcion lleva rutas, hosts y a veces la
        cadena de conexion entera; aqui solo puede ir el tipo del error.
        """
        secret = 'smtp://usuario:clave@correo-interno.local:465'

        with mock.patch(
            'apps.common.core.views.get_connection',
            side_effect=OSError(secret),
        ):
            response = self.client.get(self.url)

        self.assertNotIn(secret, response.content.decode())
        self.assertNotIn('clave', response.content.decode())

    def test_an_unexpected_failure_still_answers(self):
        """
        Si el propio health check reventara con un 500 sin cuerpo, quien lo
        vigila no sabria distinguirlo de la aplicacion entera caida.
        """
        with mock.patch(
            'apps.common.core.views.HealthCheckView._check_database',
            side_effect=RuntimeError('algo raro'),
        ):
            response = self.client.get(self.url)

        body = self.payload(response)

        self.assertEqual(response.status_code, 500)
        self.assertEqual(body['response'], 'Other Error')
