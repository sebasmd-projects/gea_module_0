# apps/project/common/account/tests_login_lockout.py
"""
Que las tres puertas del acceso cuenten en el mismo sitio.

Se puede entrar de tres formas --contraseña, codigo enviado al correo y, si lo
hay, el segundo factor-- y hasta ahora solo la primera contaba para el bloqueo
de ``django-axes``. Las otras dos no pasan por ``authenticate()``, asi que sus
fallos no llegaban a su contador.

Eso deja el freno del reves: el camino mas barato para quien ataca --probar
codigos de seis cifras, o codigos TOTP-- era justo el que no dejaba rastro,
mientras que el bloqueo solo estorbaba a quien de verdad habia olvidado su
contrasena. El tope de cinco intentos por codigo tampoco lo arregla: se
esquiva pidiendo otro codigo.

Estas pruebas fijan las dos mitades de la solucion. Que el fallo **se apunte**,
y que el bloqueo **se compruebe antes** de mirar nada -- apuntar sin comprobar
deja el bloqueo escrito en una tabla y a quien ataca dentro.

    manage.py test apps.project.common.account.tests_login_lockout \\
        --settings=app_core.settings_test
"""

from axes.models import AccessAttempt
from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.project.common.users.models import UserModel

PASSWORD = 'pw-for-tests-123'
IP = '203.0.113.5'


def code_in(outbox):
    import re
    html = outbox[-1].alternatives[0][0]
    return re.findall(r'>(\d{6})<', html)[0]


@override_settings(AXES_ENABLED=True)
class LockoutBase(TestCase):
    """``settings_test`` apaga axes; aqui se enciende, que es lo que se prueba."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        mail.outbox = []

        self.url = reverse('two_factor:login')
        self.user = UserModel.objects.create_user(
            username='ana', email='ana@example.com', password=PASSWORD,
        )

    def post(self, data):
        return self.client.post(self.url, data, REMOTE_ADDR=IP)

    def failures_recorded(self, username='ana'):
        """Cuantos intentos fallidos tiene apuntados esa pareja (IP, usuario)."""
        attempt = AccessAttempt.objects.filter(
            username=username, ip_address=IP).first()

        return attempt.failures_since_start if attempt else 0

    def ask_for_code(self, identifier='ana'):
        self.post({'use_otp': '1'})
        return self.post({
            'login_view-current_step': 'otp',
            'otp-identifier': identifier,
            'send_code': '1',
        })

    def submit_code(self, code, identifier='ana'):
        return self.post({
            'login_view-current_step': 'otp',
            'otp-identifier': identifier,
            'otp-code': code,
        })


class AWrongCodeCountsTests(LockoutBase):
    """
    El codigo por correo no puede ser la puerta barata.

    Si probar codigos no contara, quien ataca dejaria de probar contrasenas
    --que si cuentan-- y probaria codigos, que son seis cifras y no caducan
    hasta dentro de un cuarto de hora.
    """

    def test_a_wrong_code_is_recorded(self):
        self.ask_for_code()

        self.submit_code('000000')

        self.assertEqual(self.failures_recorded(), 1)

    def test_wrong_codes_reach_the_limit(self):
        self.ask_for_code()

        for _ in range(settings.AXES_FAILURE_LIMIT):
            self.submit_code('000000')

        self.assertGreaterEqual(
            self.failures_recorded(), settings.AXES_FAILURE_LIMIT)

    def test_once_locked_the_right_code_does_not_work(self):
        """
        La mitad que de verdad frena.

        Apuntar el fallo sin consultar el bloqueo lo deja escrito en una tabla
        y a quien ataca dentro: la comprobacion tiene que ir **antes** de
        comparar el codigo.
        """
        self.ask_for_code()
        good = code_in(mail.outbox)

        for _ in range(settings.AXES_FAILURE_LIMIT):
            self.submit_code('000000')

        self.submit_code(good)

        self.assertNotIn('_auth_user_id', self.client.session)

    def test_the_password_and_the_code_share_the_counter(self):
        """
        Un contador por puerta serian dos cuentas atras para el mismo intruso:
        bastaria con alternar para no agotar ninguna.
        """
        for _ in range(2):
            self.post({
                'login_view-current_step': 'auth',
                'auth-username': 'ana',
                'auth-password': 'no-es-la-buena',
            })

        self.ask_for_code()
        self.submit_code('000000')

        self.assertEqual(self.failures_recorded(), 3)


class AWrongSecondFactorCountsTests(LockoutBase):
    """
    Y el segundo factor tampoco.

    Son seis cifras que cambian cada treinta segundos, pero sin contador se
    pueden probar sin limite: lo unico que hace falta es la contrasena, que es
    justo lo que el segundo factor deberia dejar de ser suficiente.
    """

    def setUp(self):
        super().setUp()
        # El nombre importa: `two_factor.utils.default_device()` busca
        # literalmente el que se llama «default».
        TOTPDevice.objects.create(user=self.user, name='default', confirmed=True)

    def reach_the_token_step(self):
        return self.post({
            'login_view-current_step': 'auth',
            'auth-username': 'ana',
            'auth-password': PASSWORD,
        })

    def test_a_wrong_token_is_recorded(self):
        self.reach_the_token_step()

        self.post({
            'login_view-current_step': 'token',
            'token-otp_token': '000000',
        })

        self.assertEqual(self.failures_recorded(), 1)

    def test_a_wrong_token_does_not_let_anyone_in(self):
        self.reach_the_token_step()

        self.post({
            'login_view-current_step': 'token',
            'token-otp_token': '000000',
        })

        self.assertNotIn('_auth_user_id', self.client.session)
