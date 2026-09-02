# apps/project/common/account/tests_login_paths.py
"""
Los seis caminos del acceso, uno por prueba.

Hay tres puertas --contrasena, codigo al correo, y el codigo tras tres fallos--
y cada una con y sin segundo factor. Salen seis recorridos, y este fichero los
recorre enteros: no comprueba piezas sueltas sino que se llega a estar dentro,
que es lo unico que le importa a quien entra.

    1. contrasena correcta            sin 2FA -> dentro
    2. contrasena correcta            con 2FA -> pantalla del 2FA -> dentro
    3. tres fallos, luego el codigo   sin 2FA -> dentro
    4. tres fallos, luego el codigo   con 2FA -> pantalla del 2FA -> dentro
    5. codigo pedido a proposito      sin 2FA -> dentro
    6. codigo pedido a proposito      con 2FA -> pantalla del 2FA -> dentro

Y para cada uno, que el boton primario **este en la pantalla**. Eso no es
cosmetico: el asistente de la biblioteca trae un «Siguiente» generico y en una
version anterior el boton de entrar desaparecio de la primera pantalla sin que
ninguna prueba se enterara, porque todas enviaban el formulario a mano.

    manage.py test apps.project.common.account.tests_login_paths \\
        --settings=app_core.settings_test
"""

import re

from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.oath import totp

from apps.project.common.users.models import UserModel

PASSWORD = 'pw-for-tests-123'
IP = '203.0.113.5'


class LoginPathsBase(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        mail.outbox = []

        self.url = reverse('two_factor:login')
        self.user = UserModel.objects.create_user(
            username='ana', email='ana@example.com', password=PASSWORD,
        )

    # -- utilidades -----------------------------------------------------
    def post(self, data):
        return self.client.post(self.url, data, REMOTE_ADDR=IP)

    def give_a_second_factor(self):
        """
        El nombre tiene que ser «default».

        `two_factor.utils.default_device()` busca literalmente ese, que es el
        que pone el asistente de alta. Con cualquier otro nombre el dispositivo
        no cuenta como segundo factor y la prueba pasaria sin comprobar nada.
        """
        self.device = TOTPDevice.objects.create(
            user=self.user, name='default', confirmed=True)

    def valid_token(self):
        """
        El codigo que enseñaria la aplicacion en este momento, con sus ceros.

        `totp()` devuelve un **entero**, asi que uno de cada diez codigos sale
        con un digito menos --071536 se convierte en 71536-- y el formulario lo
        rechaza. Sin el relleno, estas pruebas fallaban una de cada diez veces
        sin que nada estuviera roto, que es la clase de prueba que acaba
        ignorandose.
        """
        value = totp(self.device.bin_key, self.device.step, self.device.t0,
                     self.device.digits, self.device.drift)

        return f'{value:0{self.device.digits}d}'

    def password(self, value=PASSWORD):
        return self.post({
            'login_view-current_step': 'auth',
            'auth-username': 'ana',
            'auth-password': value,
        })

    def choose_the_code(self):
        return self.post({'use_otp': '1'})

    def send_the_code(self, identifier='ana'):
        return self.post({
            'login_view-current_step': 'otp',
            'otp-identifier': identifier,
            'send_code': '1',
        })

    def enter_the_code(self, code=None, identifier='ana'):
        if code is None:
            html = mail.outbox[-1].alternatives[0][0]
            code = re.findall(r'>(\d{6})<', html)[0]

        return self.post({
            'login_view-current_step': 'otp',
            'otp-identifier': identifier,
            'otp-code': code,
        })

    def enter_the_second_factor(self):
        return self.post({
            'login_view-current_step': 'token',
            'token-otp_token': self.valid_token(),
        })

    # -- aserciones -----------------------------------------------------
    def assertInside(self):
        self.assertEqual(
            self.client.session.get('_auth_user_id'), str(self.user.pk),
            'el recorrido tenia que acabar dentro',
        )

    def assertOutside(self):
        self.assertNotIn('_auth_user_id', self.client.session)

    def assertHasButton(self, response, label):
        self.assertContains(
            response, label,
            msg_prefix=f'la pantalla no ofrece «{label}»')


class WithoutASecondFactorTests(LoginPathsBase):
    """Los tres caminos de quien no tiene segundo factor puesto."""

    def test_1_the_password_signs_in(self):
        self.password()

        self.assertInside()

    def test_3_three_failures_then_the_code_signs_in(self):
        for _ in range(3):
            offered = self.password('no-es-la-buena')

        self.assertHasButton(offered, 'Sign in')
        self.enter_the_code()

        self.assertInside()

    def test_5_choosing_the_code_signs_in(self):
        self.choose_the_code()
        self.send_the_code()
        self.enter_the_code()

        self.assertInside()


class WithASecondFactorTests(LoginPathsBase):
    """
    Los mismos tres, pero con el segundo factor puesto.

    Es la mitad que separa una comodidad de una puerta trasera: si el codigo
    dejara entrar del todo a quien tiene 2FA, bastaria con acceder a su correo
    para saltarselo. El codigo sustituye a la contrasena, no al segundo factor.
    """

    def setUp(self):
        super().setUp()
        self.give_a_second_factor()

    def test_2_the_password_asks_for_the_second_factor(self):
        self.password()
        self.assertOutside()

        self.enter_the_second_factor()

        self.assertInside()

    def test_4_the_code_after_three_failures_still_asks_for_it(self):
        for _ in range(3):
            self.password('no-es-la-buena')

        self.enter_the_code()
        self.assertOutside()

        self.enter_the_second_factor()

        self.assertInside()

    def test_6_the_chosen_code_still_asks_for_it(self):
        self.choose_the_code()
        self.send_the_code()

        self.enter_the_code()
        self.assertOutside()

        self.enter_the_second_factor()

        self.assertInside()


class EveryScreenOffersItsButtonTests(LoginPathsBase):
    """
    Que se vea cual es el boton que hace lo que se ha venido a hacer.

    El asistente de la biblioteca pinta un «Siguiente» al final y nada mas; en
    una version anterior el boton de entrar desaparecio de la primera pantalla
    y no lo noto ninguna prueba, porque todas enviaban el formulario a mano.
    """

    def test_the_password_screen_offers_signing_in(self):
        response = self.client.get(self.url)

        self.assertHasButton(response, 'Sign in')
        self.assertHasButton(response, 'Forgot your password?')

    def test_the_password_screen_offers_the_code(self):
        response = self.client.get(self.url)

        self.assertHasButton(response, 'Sign in with a code')

    def test_the_code_screen_offers_sending_and_signing_in(self):
        response = self.choose_the_code()

        self.assertHasButton(response, 'Send code')
        self.assertHasButton(response, 'Sign in')
        self.assertHasButton(response, 'Sign in with my password instead')

    def test_the_code_screen_carries_both_fields(self):
        """
        Los dos campos en la misma pantalla, que es lo que se pidio: partirlo
        en dos pasos obligaba a descubrir a mitad de camino que habia un
        segundo tramo.
        """
        response = self.choose_the_code()
        html = response.content.decode()

        self.assertIn('otp-identifier', html)
        self.assertIn('otp-code', html)

    def test_the_identifier_survives_pressing_send(self):
        """Volver a pedirlo haria dudar de si el correo llego a salir."""
        self.choose_the_code()
        response = self.send_the_code('ana')

        self.assertContains(response, 'value="ana"')

    def test_the_second_factor_screen_offers_verifying(self):
        self.give_a_second_factor()
        response = self.password()

        self.assertHasButton(response, 'Verify')

    def test_the_primary_button_comes_before_the_others(self):
        """
        El navegador dispara el **primer** boton de envio al pulsar Intro. Con
        el orden al reves, dar a Intro en la contrasena llevaba a pedir un
        codigo en vez de entrar.
        """
        html = self.client.get(self.url).content.decode()

        first_submit = html.index('type="submit"')
        use_otp = html.index('name="use_otp"')

        self.assertLess(first_submit, use_otp)
