# apps/common/utils/tests_safe_redirect.py
"""
A donde se puede mandar a alguien, y a donde no.

Un ``?next=`` sin comprobar es un redirector abierto. La comprobacion es una
linea de Django; lo que fallaba no era la comprobacion sino tenerla en un solo
sitio: estaba escrita tres veces --``set_language``, ``assets/views.py``, y
una tercera-- y **la cuarta faltaba**, justo en el wizard de registro, que es
el formulario por el que se crean cuentas y que ademas **abre la sesion**
antes de redirigir.

Las dos formas que se escapan de una comprobacion hecha a ojo tienen su prueba
propia, porque son las que de verdad se usan:

* ``//otro-sitio/`` no lleva esquema y parece una ruta.
* ``https:/otro-sitio`` con una sola barra, que algunos navegadores corrigen.

    manage.py test apps.common.utils.tests_safe_redirect \\
        --settings=app_core.settings_test
"""

from django.test import RequestFactory, SimpleTestCase

from .functions import safe_next


class SafeNextTests(SimpleTestCase):

    def setUp(self):
        self.factory = RequestFactory()

    def check(self, candidate, method='get', secure=False):
        request = getattr(self.factory, method)('/', secure=secure)

        return safe_next(request, candidate)


class TestWhatItLetsThrough(SafeNextTests):

    def test_a_plain_path(self):
        self.assertEqual(self.check('/buyer/'), '/buyer/')

    def test_a_path_with_a_query(self):
        self.assertEqual(
            self.check('/buyer/?asset=3'), '/buyer/?asset=3')

    def test_a_url_on_this_very_host(self):
        self.assertEqual(
            self.check('http://testserver/buyer/'), 'http://testserver/buyer/')


class TestWhatItRefuses(SafeNextTests):

    def test_another_site(self):
        self.assertEqual(self.check('https://sitio-ajeno.example/'), '')

    def test_a_protocol_relative_url(self):
        """
        Parece una ruta y no lo es: el navegador la resuelve como otro
        dominio. Es la forma que se cuela por una comprobacion a ojo.
        """
        self.assertEqual(self.check('//sitio-ajeno.example/'), '')

    def test_a_single_slash_scheme(self):
        """Algunos navegadores 'corrigen' `https:/x` a `https://x`."""
        self.assertEqual(self.check('https:/sitio-ajeno.example'), '')

    def test_a_javascript_url(self):
        self.assertEqual(self.check('javascript:alert(1)'), '')

    def test_a_data_url(self):
        self.assertEqual(self.check('data:text/html,<script></script>'), '')

    def test_a_lookalike_host(self):
        """`testserver.sitio-ajeno.example` no es `testserver`."""
        self.assertEqual(
            self.check('https://testserver.sitio-ajeno.example/'), '')

    def test_credentials_in_the_url(self):
        """
        `https://testserver@sitio-ajeno.example/` lleva el host bueno donde
        van las credenciales, no donde va el destino.
        """
        self.assertEqual(
            self.check('https://testserver@sitio-ajeno.example/'), '')


class TestTheFallback(SafeNextTests):

    def test_nothing_gives_the_fallback(self):
        request = self.factory.get('/')

        self.assertEqual(safe_next(request, '', fallback='/'), '/')
        self.assertEqual(safe_next(request, None, fallback='/'), '/')

    def test_a_refused_destination_gives_the_fallback(self):
        request = self.factory.get('/')

        self.assertEqual(
            safe_next(request, 'https://sitio-ajeno.example/', fallback='/'),
            '/',
        )

    def test_blanks_around_a_good_one_do_not_break_it(self):
        self.assertEqual(self.check('  /buyer/  '), '/buyer/')


class TestWhereItReadsFrom(SafeNextTests):
    """Sin candidato explicito lo saca de la peticion: POST antes que GET."""

    def test_it_reads_next_from_the_query_string(self):
        request = self.factory.get('/?next=/buyer/')

        self.assertEqual(safe_next(request), '/buyer/')

    def test_it_reads_next_from_the_body(self):
        request = self.factory.post('/', {'next': '/buyer/'})

        self.assertEqual(safe_next(request), '/buyer/')

    def test_the_body_wins_over_the_query_string(self):
        """
        El formulario que se acaba de enviar manda sobre la URL con la que se
        llego, que puede llevar un `next` de hace tres pantallas.
        """
        request = self.factory.post('/?next=/viejo/', {'next': '/nuevo/'})

        self.assertEqual(safe_next(request), '/nuevo/')

    def test_an_external_one_in_the_query_string_is_still_refused(self):
        request = self.factory.get('/?next=https://sitio-ajeno.example/')

        self.assertEqual(safe_next(request), '')


class TestOverHttps(SafeNextTests):
    """
    Sobre HTTPS no se acepta bajar a HTTP, ni siquiera al mismo host: seria
    sacar una sesion recien abierta de la conexion cifrada.
    """

    def test_http_is_refused_from_an_https_request(self):
        self.assertEqual(
            self.check('http://testserver/buyer/', secure=True), '')

    def test_https_on_this_host_is_fine(self):
        self.assertEqual(
            self.check('https://testserver/buyer/', secure=True),
            'https://testserver/buyer/',
        )

    def test_a_plain_path_is_fine(self):
        self.assertEqual(self.check('/buyer/', secure=True), '/buyer/')
