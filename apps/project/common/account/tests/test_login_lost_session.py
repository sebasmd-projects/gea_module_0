# apps/project/common/account/tests/test_login_lost_session.py
"""
Terminar el asistente sin usuario en el almacen no puede ser un 500.

El almacen de `django-two-factor-auth` guarda a quien se identifico como dos
datos sueltos --`user_pk` y `user_backend`-- y su lector
(`two_factor.views.utils.LoginStorage`) devuelve **`False`**, no `None`, cuando
falta alguno o cuando el backend ya no puede cargar esa cuenta:

    def _get_authenticated_user(self):
        if not all([self.data.get("user_pk"), self.data.get("user_backend")]):
            return False
        ...
        user = backend.get_user(self.data["user_pk"])
        if not user:
            return False

Ese `False` llegaba tal cual a `django.contrib.auth.login()`, que le busca un
atributo `backend`, no lo encuentra, y con los tres backends que configura este
proyecto termina en:

    ValueError: You have multiple authentication backends configured and
    therefore must provide the `backend` argument or set the `backend`
    attribute on the user.

O sea: la pantalla de acceso devolviendo un error del servidor, con su traza.

**Lo que estas pruebas fijan es el comportamiento, no el disparador.** El
disparador visto en un portatil no se reproduce con ninguna secuencia normal
--los seis recorridos de `test_login_paths.py` pasan, y tampoco lo provocan las
98 combinaciones de dos y tres acciones que se probaron a mano--: hace falta
que el almacen pierda al usuario entre dos peticiones, lo que puede venir de
una sesion caida, de una sesion a medias de una version anterior o de una
cuenta que dejo de poder cargarse entre identificarse y terminar.

Por eso se prueba la condicion directamente: **pase lo que pase antes**, si al
terminar no hay usuario, no se entra, se vuelve a la pantalla de acceso y se
dice. Un `login()` con `False` dentro no es una posibilidad.

    manage.py test apps.project.common.account.tests.test_login_lost_session \\
        --settings=app_core.settings_test
"""

from unittest.mock import patch

from django.contrib.messages import get_messages
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.project.common.account.login_view import GeaLoginView
from apps.project.common.users.models import UserModel

PASSWORD = 'pw-for-tests-123'
IP = '203.0.113.9'


class LoginWithoutUserInStorageTests(TestCase):
    """
    Se fuerza el unico dato que importa: `get_user()` sin usuario.

    Se parchea el lector y no la sesion porque es donde nace el problema --el
    almacen contesta `False`-- y porque asi la prueba vale para las tres formas
    de llegar ahi, en vez de para la que se supo reproducir.
    """

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

        self.url = reverse('two_factor:login')
        self.user = UserModel.objects.create_user(
            username='bruno', email='bruno@example.com', password=PASSWORD,
        )

    def _sign_in_without_user_in_storage(self):
        self.client.get(self.url)

        with patch.object(GeaLoginView, 'get_user', return_value=False):
            return self.client.post(self.url, {
                'login_view-current_step': 'auth',
                'auth-username': 'bruno@example.com',
                'auth-password': PASSWORD,
            }, REMOTE_ADDR=IP)

    # ------------------------------------------------------------------
    def test_no_revienta_y_vuelve_a_la_pantalla_de_acceso(self):
        response = self._sign_in_without_user_in_storage()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], self.url)

    def test_no_deja_una_sesion_autenticada(self):
        """
        Lo importante: sin usuario no se entra. Ni a medias.
        """
        self._sign_in_without_user_in_storage()

        self.assertNotIn('_auth_user_id', self.client.session)

    def test_se_avisa_en_pantalla(self):
        """
        Un reinicio callado es indistinguible de un boton que no hace nada.
        """
        response = self._sign_in_without_user_in_storage()

        avisos = ' '.join(
            str(m) for m in get_messages(response.wsgi_request)
        ).lower()

        self.assertIn('session', avisos)

    def test_el_asistente_queda_utilizable(self):
        """
        Reiniciar tiene que dejarlo listo, no encallado: el intento siguiente
        --ya sin el problema-- entra con normalidad.
        """
        self._sign_in_without_user_in_storage()

        self.client.get(self.url)
        response = self.client.post(self.url, {
            'login_view-current_step': 'auth',
            'auth-username': 'bruno@example.com',
            'auth-password': PASSWORD,
        }, REMOTE_ADDR=IP)

        self.assertEqual(response.status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)

    def test_el_modo_vuelve_al_de_contrasena(self):
        """
        Si se venia del rodeo del codigo, el asistente no puede quedarse ahi:
        la pantalla siguiente seria la del codigo, sin codigo que meter.
        """
        self._sign_in_without_user_in_storage()

        self.assertEqual(
            self.client.session.get('login_mode', 'password'), 'password'
        )
