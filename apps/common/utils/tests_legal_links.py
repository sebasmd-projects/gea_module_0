# apps/common/utils/tests_legal_links.py
"""
Que a los documentos legales y al PQRS se llegue desde alguna parte.

Los cuatro documentos --politica de datos, privacidad, cookies, terminos-- y
el formulario de PQRS existian, respondian 200 y no estaban enlazados en
ningun sitio. Los enlaces del pie estaban escritos, pero **dentro de un
``{% comment %}``**, en los dos pies que habia. Asi que en toda la plataforma
no habia forma de llegar a ellos si no te sabias la URL.

Un documento al que no se llega no cumple: la Ley 1581 exige que el titular
pueda ejercer sus derechos y el articulo 23 de la Constitucion que pueda
peticionar, y ninguna de las dos cosas se satisface con una URL que solo
conoce quien leyo el codigo.

Estas pruebas fijan que se llegue desde donde importa: la portada --la unica
pagina que ve alguien sin cuenta--, el login y el registro.

    manage.py test apps.common.utils.tests_legal_links \\
        --settings=app_core.settings_test
"""

from django.test import TestCase
from django.urls import reverse

#: Lo que tiene que estar alcanzable desde cualquier pagina de entrada.
LEGAL_ROUTES = (
    'pqrs:new',
    'core:data_policy',
    'core:privacy',
    'core:cookies',
    'core:terms',
)

#: Las paginas por las que entra alguien que todavia no tiene cuenta.
ENTRY_POINTS = (
    'core:index',
    'account:register',
)


class LegalPagesAnswerTests(TestCase):
    """Primero, que existan. Sin esto lo demas no significa nada."""

    def test_every_legal_page_answers(self):
        for name in LEGAL_ROUTES:
            with self.subTest(route=name):
                response = self.client.get(reverse(name))

                self.assertEqual(response.status_code, 200)


class LegalLinksAreReachableTests(TestCase):
    """
    Y segundo, que se llegue. Que es lo que fallaba.
    """

    def assert_links_present(self, url):
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        html = response.content.decode()

        for name in LEGAL_ROUTES:
            with self.subTest(page=url, route=name):
                self.assertIn(
                    f'href="{reverse(name)}"', html,
                    f'{url} no enlaza a {name}',
                )

    def test_the_landing_page_links_them(self):
        """
        La portada es la que mas importa: es la unica pagina que ve alguien
        que no tiene cuenta, y quien pide que le supriman sus datos por
        definicion no quiere tenerla. No tenia pie de ninguna clase.
        """
        self.assert_links_present(reverse('core:index'))

    def test_the_login_page_links_them(self):
        self.assert_links_present(reverse('two_factor:login'))

    def test_the_register_page_links_them(self):
        """
        Aqui hace falta ademas por otro motivo: es donde se acepta el
        tratamiento de datos, y aceptar algo que no se puede leer no es
        aceptar.
        """
        self.assert_links_present(reverse('account:register'))


class RegisterPointsAtTheLoginTests(TestCase):
    """
    "¿Ya tienes una cuenta? Entra" llevaba al registro.

    El `href` estaba vacio, y un href vacio recarga la pagina actual. Como la
    pagina actual **es** el registro, el enlace parecia funcionar --la pantalla
    cambia, se recarga-- y devolvia al mismo formulario. Que sea el paso 1 otra
    vez lo hace todavia mas confuso: parece que se ha perdido lo escrito.
    """

    def test_the_sign_in_link_goes_to_the_login(self):
        response = self.client.get(reverse('account:register'))
        html = response.content.decode()

        self.assertIn(f'href="{reverse("two_factor:login")}"', html)

    def test_there_is_no_empty_href_left(self):
        response = self.client.get(reverse('account:register'))

        self.assertNotIn('href=""', response.content.decode())


class RegisterShowsItsStepsTests(TestCase):
    """
    El registro decia solo "Paso 1 / 4".

    Eso dice cuantos faltan, pero no de que van. Y el ultimo paso pide un
    codigo que llega por correo o que da un asesor: saber que eso viene al
    final decide si se empieza ahora o cuando se tenga el codigo delante.
    """

    def test_the_step_names_are_shown(self):
        response = self.client.get(reverse('account:register'))
        html = response.content.decode()

        self.assertIn('wizard-steps', html)
        self.assertIn('Verification code', html)

    def test_the_current_step_is_marked(self):
        """Para un lector de pantalla, y para el que solo ve el color."""
        response = self.client.get(reverse('account:register'))

        self.assertIn('aria-current="step"', response.content.decode())
