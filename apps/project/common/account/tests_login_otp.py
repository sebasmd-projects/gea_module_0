# apps/project/common/account/tests_login_otp.py
"""
Entrar con un código enviado al correo.

Lo que se fija aqui no es que la pantalla funcione --eso se ve mirandola--
sino las cuatro cosas que, si se rompen, no se notan hasta que alguien las
aprovecha:

* que el codigo **no sustituye al segundo factor** de quien lo tiene puesto;
* que preguntar por un usuario **no dice si existe**;
* que el codigo vale una vez, caduca, y se tira tras varios fallos;
* que el envio pasa por su cupo y **falla cerrado**.

    manage.py test apps.project.common.account.tests_login_otp \\
        --settings=app_core.settings_test
"""

from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.common.utils.tests_throttling import dead_cache
from apps.project.common.users.models import UserModel

from . import login_view, otp_login

PASSWORD = 'pw-for-tests-123'
IP = '203.0.113.5'


def codes_in(outbox):
    """Los codigos de seis cifras que salieron por correo."""
    import re
    found = []
    for message in outbox:
        # Solo el HTML: el mismo codigo sale tambien en el cuerpo de texto, y
        # contarlo dos veces haria creer que se mandaron dos correos.
        html = message.alternatives[0][0] if message.alternatives else message.body
        found += re.findall(r'>(\d{6})<', html) or re.findall(r'\b(\d{6})\b', html)
    return found


class LoginOTPMixin:

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        mail.outbox = []

        self.url = reverse('two_factor:login')
        self.user = UserModel.objects.create_user(
            username='ana', email='ana@example.com', password=PASSWORD,
        )

    def post(self, data, **extra):
        return self.client.post(self.url, data, REMOTE_ADDR=IP, **extra)

    def ask_for_code(self, identifier='ana'):
        """Pulsa «entrar con un código» y luego «enviar» para ese usuario."""
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


class TheCodeArrivesAndWorksTests(LoginOTPMixin, TestCase):
    """La mitad que tiene que funcionar."""

    def test_asking_for_a_code_sends_one(self):
        self.ask_for_code()

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['ana@example.com'])
        self.assertEqual(len(codes_in(mail.outbox)), 1)

    def test_the_code_signs_the_user_in(self):
        self.ask_for_code()
        code = codes_in(mail.outbox)[0]

        self.submit_code(code)

        self.assertEqual(
            self.client.session.get('_auth_user_id'), str(self.user.pk))

    def test_the_email_address_works_too(self):
        self.ask_for_code('ana@example.com')

        self.assertEqual(len(mail.outbox), 1)

    def test_the_email_carries_the_logos_inside(self):
        """
        Incrustados, no enlazados: un `src` remoto lo bloquea Gmail y el
        mensaje llega con dos huecos rotos justo encima del código.
        """
        self.ask_for_code()
        message = mail.outbox[0]

        html = message.alternatives[0][0]

        self.assertIn('cid:propensiones', html)
        self.assertIn('cid:gea', html)
        self.assertNotIn('<img src="http', html)

    def test_the_email_says_the_expiry_and_who_to_call(self):
        self.ask_for_code()
        html = mail.outbox[0].alternatives[0][0]

        self.assertIn(str(otp_login.ttl_minutes()), html)
        self.assertIn('info@propensionesabogados.com', html)
        self.assertIn('target="_blank"', html)


class TheCodeIsNotASecondKeyTests(LoginOTPMixin, TestCase):
    """
    Lo que separa una comodidad de una puerta trasera.

    Si el código dejara entrar del todo a quien tiene el segundo factor
    puesto, bastaría con acceder a su correo para saltárselo. El código
    sustituye a la contraseña, no al segundo factor.
    """

    def test_a_user_with_a_device_still_gets_the_token_step(self):
        from django_otp.plugins.otp_totp.models import TOTPDevice

        # El nombre importa: `two_factor.utils.default_device()` busca
        # literalmente el que se llama «default», que es el que pone el
        # asistente de alta. Uno con cualquier otro nombre no cuenta como
        # segundo factor y esta prueba pasaría sin comprobar nada.
        TOTPDevice.objects.create(user=self.user, name='default', confirmed=True)

        self.ask_for_code()
        response = self.submit_code(codes_in(mail.outbox)[0])

        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertContains(response, 'token')

    def test_without_a_device_the_code_is_enough(self):
        self.ask_for_code()
        self.submit_code(codes_in(mail.outbox)[0])

        self.assertIn('_auth_user_id', self.client.session)


class ItDoesNotSayWhoExistsTests(LoginOTPMixin, TestCase):
    """
    Preguntar por una cuenta no puede contestar si la hay.

    Lo contrario convierte la pantalla en un comprobador de cuentas: se prueba
    una lista de correos y se apunta cuáles contestan distinto.
    """

    def test_an_unknown_identifier_looks_the_same(self):
        known = self.ask_for_code('ana')
        self.client.logout()
        cache.clear()
        mail.outbox = []
        unknown = self.ask_for_code('no-existe-en-absoluto')

        self.assertEqual(known.status_code, unknown.status_code)
        self.assertIn('otp-code', unknown.content.decode())

    def test_no_email_goes_out_for_an_unknown_identifier(self):
        self.ask_for_code('no-existe-en-absoluto')

        self.assertEqual(len(mail.outbox), 0)

    def test_a_wrong_code_says_the_same_for_both(self):
        self.ask_for_code('no-existe-en-absoluto')
        unknown = self.submit_code('000000', 'no-existe-en-absoluto')

        self.assertEqual(unknown.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_an_inactive_account_gets_nothing(self):
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])

        self.ask_for_code()

        self.assertEqual(len(mail.outbox), 0)


class TheCodeIsSpentAndExpiresTests(LoginOTPMixin, TestCase):

    def test_it_only_works_once(self):
        self.ask_for_code()
        code = codes_in(mail.outbox)[0]
        self.submit_code(code)
        self.client.logout()

        self.submit_code(code)

        self.assertNotIn('_auth_user_id', self.client.session)

    def test_an_expired_code_is_refused(self):
        self.ask_for_code()
        code = codes_in(mail.outbox)[0]

        session = self.client.session
        state = session[otp_login.SESSION_KEY]
        state['expires_at'] = (
            timezone.now() - timezone.timedelta(seconds=1)).isoformat()
        session[otp_login.SESSION_KEY] = state
        session.save()

        self.submit_code(code)

        self.assertNotIn('_auth_user_id', self.client.session)

    def test_too_many_wrong_codes_throw_the_code_away(self):
        """
        Se tira el código, no solo se corta la pantalla: un tope que sólo
        cerrara la sesión lo esquiva quien borre la cookie.
        """
        self.ask_for_code()
        code = codes_in(mail.outbox)[0]

        for _ in range(otp_login.MAX_ATTEMPTS + 1):
            self.submit_code('000000')

        self.submit_code(code)

        self.assertNotIn('_auth_user_id', self.client.session)

    def test_the_code_is_never_stored_in_the_clear(self):
        self.ask_for_code()
        code = codes_in(mail.outbox)[0]

        stored = self.client.session[otp_login.SESSION_KEY]

        self.assertNotIn(code, str(stored))
        self.assertEqual(stored['code_hash'], otp_login.hash_code(code))


class ThreeWrongPasswordsOfferTheCodeTests(LoginOTPMixin, TestCase):
    """
    Lo que pidió el encargo: al tercer fallo, el código, para llegar antes
    que el bloqueo de axes --seis intentos por defecto, media hora fuera.
    """

    def wrong_password(self):
        return self.post({
            'login_view-current_step': 'auth',
            'auth-username': 'ana',
            'auth-password': 'no-es-la-buena',
        })

    def test_the_first_two_just_fail(self):
        self.wrong_password()
        response = self.wrong_password()

        self.assertEqual(len(mail.outbox), 0)
        self.assertIn('auth', response.content.decode())

    def test_the_third_sends_a_code(self):
        for _ in range(3):
            response = self.wrong_password()

        self.assertEqual(len(mail.outbox), 1)
        self.assertContains(response, 'one-time code has been sent')

    def test_the_username_is_shown_back(self):
        for _ in range(3):
            response = self.wrong_password()

        self.assertContains(response, 'ana')

    def test_that_code_signs_in(self):
        for _ in range(3):
            self.wrong_password()

        self.submit_code(codes_in(mail.outbox)[0])

        self.assertIn('_auth_user_id', self.client.session)

    def test_the_offer_does_not_cap_the_attempts(self):
        """
        La oferta es un aviso, no un tope.

        Si al ofrecer el código el paso de contraseña saliera de la lista, el
        cuarto envío no llegaría a validarse: `django-axes` no contaría ese
        fallo y su bloqueo --seis intentos-- no se alcanzaría nunca desde el
        navegador. La comodidad habría apagado el freno.
        """
        for _ in range(6):
            self.wrong_password()

        self.assertEqual(
            self.client.session.get(login_view.FAILURES_KEY), 6,
            'los intentos de contraseña siguen contando después de la oferta',
        )

    def test_it_is_offered_once(self):
        """
        Quien pide volver a la contraseña no puede acabar otra vez en la
        pantalla del código a cada fallo: no llegaría a gastar el intento.
        """
        for _ in range(6):
            self.wrong_password()

        self.assertEqual(len(mail.outbox), 1)

    def test_the_right_password_ends_the_detour(self):
        """
        Acertar cierra el rodeo. Con el modo puesto, los pasos del código
        seguirían en la lista y el asistente pediría un correo justo después
        de identificarse con la contraseña.
        """
        for _ in range(3):
            self.wrong_password()

        self.post({
            'login_view-current_step': 'auth',
            'auth-username': 'ana',
            'auth-password': PASSWORD,
        })

        self.assertIn('_auth_user_id', self.client.session)


class SendingIsRateLimitedTests(LoginOTPMixin, TestCase):

    def test_the_quota_stops_the_flood(self):
        """
        Sin esto, teclear el usuario de otro y pedir código en bucle le llena
        el buzón: quien recibe no eligió nada.
        """
        for _ in range(8):
            self.ask_for_code()

        self.assertLessEqual(len(mail.outbox), otp_login.send_throttle.limit)

    def test_with_the_cache_down_nothing_is_sent(self):
        """
        Falla cerrado. El correo sale hacia el buzón de otra persona, así que
        si el contador no se puede llevar no se manda -- el mismo criterio que
        en la recuperación de contraseña.
        """
        with dead_cache():
            self.ask_for_code()

        self.assertEqual(len(mail.outbox), 0)
