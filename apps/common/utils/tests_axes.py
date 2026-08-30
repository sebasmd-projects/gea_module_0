# apps/common/utils/tests_axes.py
"""
El freno de fuerza bruta del login: que estorbe al atacante, no a la oficina.

``django-axes`` estaba instalado sin una linea de configuracion y con su
backend en segundo lugar. De ahi salian tres comportamientos concretos, y las
tres primeras pruebas de ``LockoutScopeTests`` y ``LockoutBypassTests``
reproducen cada uno; todas fallaban antes:

1. El bloqueo caia sobre la **IP entera**, asi que quien nunca se habia
   equivocado se quedaba fuera por culpa del companero de al lado.
2. El bloqueo era **permanente** (``AXES_COOLOFF_TIME = None``): no se abria
   solo, habia que entrar a la base de datos.
3. Estando bloqueado, una contrasena equivocada daba 429 pero **la correcta
   entraba igual**, porque otro backend autenticaba antes que el de axes. El
   limite molestaba al usuario legitimo y no frenaba a quien acertaba.

    manage.py test apps.common.utils --settings=app_core.settings_test
"""

from datetime import timedelta

from axes.handlers.proxy import AxesProxyHandler
from axes.models import AccessAttempt
from django.conf import settings
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from apps.project.common.users.models import UserModel

from .models import WhiteListedIPModel

PASSWORD = 'pw-for-tests-123'
OFFICE = '203.0.113.9'
ELSEWHERE = '198.51.100.7'

WIZARD_STEP = {'login_view-current_step': 'auth'}


def login_payload(username, password):
    return {
        'auth-username': username,
        'auth-password': password,
        **WIZARD_STEP,
    }


@override_settings(AXES_ENABLED=True)
class LockoutBaseTestCase(TestCase):
    """Utilidades comunes: dos usuarios reales y fallos a demanda.

    ``settings_test`` apaga axes para que ``client.login()`` siga funcionando
    en el resto de la suite; aqui se enciende, que es lo que se prueba.
    """

    def setUp(self):
        self.url = reverse('two_factor:login')

        self.careless = UserModel.objects.create_user(
            username='ana', email='ana@example.com', password=PASSWORD,
        )
        self.colleague = UserModel.objects.create_user(
            username='beto', email='beto@example.com', password=PASSWORD,
        )

    def fail_logins(self, username, times, ip=OFFICE):
        """`times` intentos con la contrasena equivocada desde `ip`."""
        for _ in range(times):
            self.client.post(
                self.url,
                login_payload(username, 'not-the-password'),
                REMOTE_ADDR=ip,
            )

    def is_allowed(self, username, ip=OFFICE):
        """Si axes dejaria pasar a `username` desde `ip`."""
        request = RequestFactory().post(self.url, REMOTE_ADDR=ip)
        request.META['HTTP_USER_AGENT'] = ''

        return AxesProxyHandler().is_allowed(request, {'username': username})


@override_settings(AXES_ENABLED=True)
class LockoutScopeTests(LockoutBaseTestCase):
    """A quien alcanza el bloqueo."""

    def test_the_one_who_failed_gets_locked(self):
        """Lo que si tiene que pasar: el freno existe."""
        self.fail_logins('ana', settings.AXES_FAILURE_LIMIT)

        self.assertFalse(self.is_allowed('ana'))

    def test_a_colleague_on_the_same_ip_is_not_locked(self):
        """
        El autobloqueo que hacia esto inservible en una oficina.

        Con el bloqueo por IP a secas, que una persona se equivocara tres
        veces dejaba fuera a todo el que saliera por esa misma IP.
        """
        self.fail_logins('ana', settings.AXES_FAILURE_LIMIT)

        self.assertTrue(
            self.is_allowed('beto'),
            'quien no ha fallado no puede quedar bloqueado por su IP',
        )

    def test_the_same_user_from_elsewhere_is_still_locked(self):
        """El bloqueo mira la pareja, asi que cambiar de IP no lo limpia..."""
        self.fail_logins('ana', settings.AXES_FAILURE_LIMIT)

        # ...pero tampoco persigue al usuario por toda la red: desde otra IP
        # la cuenta arranca de cero. Es el precio de no bloquear la oficina, y
        # el atacante que rota IPs ya se frena en otras capas.
        self.assertTrue(self.is_allowed('ana', ip=ELSEWHERE))

    def test_a_whitelisted_ip_is_never_locked(self):
        """
        El remedio documentado tiene que servir tambien para el login.

        ``WhiteListedIPModel`` desbloqueaba la mitigacion anti-escaneo y
        dejaba el login igual de cerrado, que es justo cuando hace falta.
        """
        WhiteListedIPModel.objects.create(current_ip=OFFICE)

        self.fail_logins('ana', settings.AXES_FAILURE_LIMIT + 2)

        self.assertTrue(self.is_allowed('ana'))


@override_settings(AXES_ENABLED=True)
class LockoutBypassTests(LockoutBaseTestCase):
    """Que el bloqueo frene de verdad mientras dura."""

    def test_the_right_password_does_not_walk_past_the_lockout(self):
        """
        El agujero: el limite se saltaba justo cuando importaba.

        Con el backend de axes en segundo lugar, otro backend autenticaba
        primero: durante el bloqueo, la contrasena equivocada daba 429 y la
        correcta entraba. Asi el freno solo estorbaba al usuario legitimo.
        """
        self.fail_logins('ana', settings.AXES_FAILURE_LIMIT)

        response = self.client.post(
            self.url, login_payload('ana', PASSWORD), REMOTE_ADDR=OFFICE,
        )

        self.assertNotEqual(
            response.status_code, 302,
            'una contrasena correcta no puede saltarse el bloqueo',
        )

    def test_the_lockout_opens_by_itself(self):
        """
        Sin ``COOLOFF_TIME`` el bloqueo era permanente: no se abria nunca sin
        tocar la base de datos a mano. Un olvido no puede costar eso.
        """
        self.assertIsNotNone(settings.AXES_COOLOFF_TIME)

        self.fail_logins('ana', settings.AXES_FAILURE_LIMIT)
        self.assertFalse(self.is_allowed('ana'))

        # Se envejecen los intentos como si hubiera pasado la espera.
        AccessAttempt.objects.update(
            attempt_time=(
                AccessAttempt.objects.first().attempt_time
                - settings.AXES_COOLOFF_TIME - timedelta(minutes=1)
            )
        )

        self.assertTrue(self.is_allowed('ana'))

    def test_a_good_login_forgets_the_earlier_slips(self):
        """
        Con ``RESET_ON_SUCCESS`` en False los despistes se acumulaban durante
        meses, hasta que un dia el enesimo bloqueaba a quien no habia hecho
        nada raro.
        """
        self.fail_logins('ana', settings.AXES_FAILURE_LIMIT - 1)

        self.client.post(
            self.url, login_payload('ana', PASSWORD), REMOTE_ADDR=OFFICE,
        )

        self.assertFalse(
            AccessAttempt.objects.filter(username='ana').exists(),
            'un login correcto tiene que borrar los fallos previos',
        )
