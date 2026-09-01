# apps/project/common/account/tests_login.py
"""
El login, que no tenia ninguna prueba directa.

Es el camino mas critico del producto y el mas facil de romper sin enterarse,
porque no es un formulario: es un wizard de ``formtools`` con dos pasos
(credenciales y segundo factor), servido por ``django-two-factor-auth``. Eso
tiene dos consecuencias que ya han mordido en este proyecto:

* **El campo no se llama ``username``, se llama ``auth-username``.** De ahi
  que haga falta ``AXES_USERNAME_CALLABLE``: sin el, axes guarda todos los
  intentos con usuario vacio y el bloqueo por pareja (IP, usuario) degrada en
  silencio a bloqueo por IP.
* **El correo va cifrado**, asi que la busqueda por ``email`` no encuentra
  nada. Quien hace funcionar el login es ``EmailOrUsernameModelBackend``, que
  busca por ``email_hash``.

Estas pruebas se anadieron al quitar ``betterforms`` de ``INSTALLED_APPS``:
lo arrastraba una version vieja de ``django-two-factor-auth`` y ya nadie lo
usaba, pero comprobar que el login sigue en pie despues de tocar sus
dependencias no puede quedar en "lo he probado a mano una vez".

    manage.py test apps.project.common.account.tests_login \\
        --settings=app_core.settings_test
"""

from django.test import TestCase
from django.urls import reverse

from apps.project.common.users.models import UserModel

PASSWORD = 'una-clave-larga-de-prueba-123'


class LoginMixin:

    @classmethod
    def setUpTestData(cls):
        cls.user = UserModel.objects.create_user(
            username='ana', email='ana@example.com', password=PASSWORD,
            first_name='Ana', last_name='Lopez',
        )

    def setUp(self):
        self.url = reverse('two_factor:login')

    def submit(self, username, password=PASSWORD):
        return self.client.post(self.url, {
            # El prefijo lo pone el wizard. Si algun dia cambia, hay que
            # actualizar tambien `USERNAME_FIELDS` de `utils/axes_hooks.py`,
            # o los bloqueos por pareja (IP, usuario) dejan de funcionar sin
            # avisar.
            'login_view-current_step': 'auth',
            'auth-username': username,
            'auth-password': password,
        })


class TestTheLoginPageWorks(LoginMixin, TestCase):

    def test_it_renders(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

    def test_it_carries_the_wizard_step_field(self):
        """
        Sin este campo el wizard responde 400 y nadie entra. Es lo primero que
        se rompe al tocar la plantilla del login.
        """
        response = self.client.get(self.url)

        self.assertContains(response, 'login_view-current_step')

    def test_the_credential_fields_keep_their_prefix(self):
        response = self.client.get(self.url)

        self.assertContains(response, 'auth-username')
        self.assertContains(response, 'auth-password')


class TestGettingIn(LoginMixin, TestCase):

    def test_with_the_username(self):
        response = self.submit('ana')

        self.assertEqual(response.status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)

    def test_with_the_email(self):
        """
        Lo que no funcionaria con el backend de Django a secas: el correo esta
        cifrado y `filter(email=...)` no encuentra nada.
        """
        response = self.submit('ana@example.com')

        self.assertEqual(response.status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)

    def test_with_the_email_in_another_case(self):
        self.submit('Ana@Example.COM')

        self.assertIn('_auth_user_id', self.client.session)


class TestStayingOut(LoginMixin, TestCase):

    def test_a_wrong_password(self):
        self.submit('ana', 'no-es-la-clave')

        self.assertNotIn('_auth_user_id', self.client.session)

    def test_an_unknown_account(self):
        self.submit('nadie@example.com')

        self.assertNotIn('_auth_user_id', self.client.session)

    def test_a_deactivated_account(self):
        """
        Dar de baja es poner `is_active = False`: el borrado en esta
        plataforma es logico. Si eso no cortara el login, dar de baja no
        serviria de nada.
        """
        self.user.is_active = False
        self.user.save()

        self.submit('ana')

        self.assertNotIn('_auth_user_id', self.client.session)

    def test_the_answer_does_not_say_which_half_failed(self):
        """
        Un mensaje distinto para "no existe" y para "la clave no es" convierte
        el formulario en un comprobador de cuentas.
        """
        unknown = self.submit('nadie@example.com')
        wrong = self.submit('ana', 'no-es-la-clave')

        self.assertEqual(unknown.status_code, wrong.status_code)


class TestLoggingOut(LoginMixin, TestCase):

    def test_it_closes_the_session(self):
        self.submit('ana')
        self.assertIn('_auth_user_id', self.client.session)

        self.client.get(reverse('account:logout'))

        self.assertNotIn('_auth_user_id', self.client.session)
