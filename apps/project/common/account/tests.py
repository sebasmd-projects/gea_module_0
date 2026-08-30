# apps/project/common/account/tests.py
"""
Recuperacion de contrasena: el unico formulario que manda correo sin sesion.

Eso lo convierte en tres cosas a la vez -- un altavoz para llenar la bandeja de
otro, un oraculo para averiguar quien tiene cuenta, y un generador de enlaces
que llegan a un correo ajeno --, y cada prueba de aqui fija una. Todas fallaban
antes.

    manage.py test apps.project.common.account --settings=app_core.settings_test
"""

from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.project.common.users.models import UserModel

from .views import ForgotPasswordFormView

PASSWORD = 'pw-for-tests-123'
SOMEONE = '203.0.113.9'

# Los cupos se leen de la vista para no repetir los numeros aqui.
PER_TARGET = ForgotPasswordFormView.RESET_MAX_SENDS_PER_TARGET
PER_IP = ForgotPasswordFormView.RESET_MAX_SENDS_PER_IP


class PasswordResetRateLimitTests(TestCase):
    """Que no se pueda usar el formulario como altavoz."""

    def setUp(self):
        cache.clear()
        self.url = reverse('account:forgot_password')
        self.victim = UserModel.objects.create_user(
            username='ana', email='ana@example.com', password=PASSWORD,
        )

    def request_reset(self, identifier, ip=SOMEONE):
        return self.client.post(
            self.url, {'email_or_username': identifier}, REMOTE_ADDR=ip,
        )

    def test_a_mailbox_cannot_be_flooded(self):
        """
        El ataque completo: repetir el formulario con el correo de otro hasta
        llenarle la bandeja, y de paso quemar la cuota del proveedor.
        """
        for _ in range(12):
            self.request_reset('ana@example.com')

        self.assertLessEqual(
            len(mail.outbox),
            PER_TARGET,
            'el cupo por destinatario tiene que cortar el envio',
        )

    def test_changing_the_target_does_not_dodge_the_limit(self):
        """
        Sin cupo por IP bastaria con ir cambiando de destinatario para seguir
        mandando correos desde el mismo sitio.
        """
        for index in range(20):
            UserModel.objects.create_user(
                username=f'user{index}',
                email=f'user{index}@example.com',
                password=PASSWORD,
            )
            self.request_reset(f'user{index}@example.com')

        self.assertLessEqual(
            len(mail.outbox),
            PER_IP,
            'el cupo por IP tiene que cortar el goteo',
        )

    def test_another_ip_keeps_its_own_quota(self):
        """El limite frena a quien abusa, no al siguiente que llega."""
        for _ in range(PER_TARGET + 2):
            self.request_reset('ana@example.com')

        sent_before = len(mail.outbox)

        self.request_reset('ana@example.com', ip='198.51.100.7')

        self.assertEqual(
            len(mail.outbox), sent_before + 1,
            'una IP distinta no puede heredar el bloqueo de otra',
        )


class PasswordResetDoesNotLeakAccountsTests(TestCase):
    """Que la respuesta no diga quien tiene cuenta."""

    def setUp(self):
        cache.clear()
        self.url = reverse('account:forgot_password')
        UserModel.objects.create_user(
            username='ana', email='ana@example.com', password=PASSWORD,
        )

    def post(self, identifier):
        return self.client.post(
            self.url, {'email_or_username': identifier}, REMOTE_ADDR=SOMEONE,
        )

    def test_an_existing_and_an_unknown_account_look_the_same(self):
        existing = self.post('ana@example.com')
        cache.clear()
        unknown = self.post('nadie@example.com')

        self.assertEqual(existing.status_code, unknown.status_code)
        self.assertEqual(existing.content, unknown.content)

    def test_running_out_of_quota_looks_the_same_too(self):
        """
        Si al agotar el cupo la pantalla cambiara, esa diferencia volveria a
        ser un oraculo: solo se agota el cupo de quien existe.
        """
        first = self.post('ana@example.com')

        for _ in range(PER_TARGET + 3):
            self.post('ana@example.com')

        exhausted = self.post('ana@example.com')

        self.assertEqual(first.status_code, exhausted.status_code)
        self.assertEqual(first.content, exhausted.content)

    def test_a_broken_mail_server_does_not_give_the_answer_away(self):
        """
        Con ``fail_silently=False``, un fallo de SMTP daba 500 a quien existe y
        pagina normal a quien no. Es el oraculo mas ruidoso de todos.
        """
        with self.settings(
            EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend',
            EMAIL_HOST='127.0.0.1',
            EMAIL_PORT=1,
        ):
            response = self.post('ana@example.com')

        self.assertEqual(response.status_code, 200)


class PasswordResetLinkTests(TestCase):
    """De donde sale el enlace que acaba en el correo de alguien."""

    def setUp(self):
        cache.clear()
        self.url = reverse('account:forgot_password')
        self.user = UserModel.objects.create_user(
            username='ana', email='ana@example.com', password=PASSWORD,
        )

    def test_the_link_ignores_the_host_header(self):
        """
        La invariante 12 aplicada al peor sitio posible.

        ``django.contrib.sites`` no esta instalado, asi que ``get_current_site``
        devolvia un RequestSite con la cabecera Host -- que la pone el cliente.
        Un enlace de restablecimiento construido con ella es un enlace de
        restablecimiento apuntando al dominio del atacante, entregado por
        nuestro propio servidor en el correo de la victima.
        """
        with self.settings(ALLOWED_HOSTS=['*']):
            self.client.post(
                self.url,
                {'email_or_username': 'ana@example.com'},
                REMOTE_ADDR=SOMEONE,
                HTTP_HOST='atacante.example.net',
            )

        self.assertEqual(len(mail.outbox), 1)

        body = mail.outbox[0].body

        self.assertNotIn('atacante.example.net', body)
        self.assertIn(settings.PUBLIC_BASE_URL, body)
