# app_core/tests_admin.py
"""
La puerta del admin: se entra con sesion, no sabiendo la URL.

Antes lo unico que separaba a un desconocido del panel era desconocer
``ADMIN_URL``. Con la ruta en la mano, la respuesta del servidor confirmaba el
hallazgo -- un formulario de login del admin, o una redireccion a el -- y a
partir de ahi solo faltaban credenciales. Cada prueba de aqui fija una de las
cuatro respuestas posibles, que es lo que decide si la ruta sigue siendo un
secreto que importa:

    manage.py test app_core --settings=app_core.settings_test
"""

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from apps.common.utils.testing import login_with_otp
from apps.project.common.users.models import UserModel

PASSWORD = 'pw-for-tests-123'


class AdminDoorTests(TestCase):
    """Quien recibe que al llamar a la puerta del panel."""

    def setUp(self):
        self.index = reverse('admin:index')
        self.login_url = reverse('admin:login')

    def make_user(self, username, *, staff=False):
        return UserModel.objects.create_user(
            username=username,
            email=f'{username}@example.com',
            password=PASSWORD,
            is_staff=staff,
            is_superuser=staff,
        )

    def verify_otp(self, user):
        """Deja la sesion como la deja el segundo factor de verdad."""
        login_with_otp(self.client, user)

    def test_a_stranger_is_not_told_the_panel_exists(self):
        """
        El fallo de fondo: la propia respuesta confirmaba el hallazgo.

        Con la ruta adivinada o filtrada, un 302 al login del admin -- o el
        formulario -- avisan de que ahi hay un panel. Un 404 no.
        """
        response = self.client.get(self.index)

        self.assertEqual(response.status_code, 404)

    def test_the_admin_login_form_is_not_served_either(self):
        """
        No vale esconder el indice y dejar el login a la vista: el formulario
        del admin es igual de reconocible, y era la segunda puerta con sus
        propias reglas.
        """
        response = self.client.get(self.login_url)

        self.assertEqual(response.status_code, 404)

    def test_an_ordinary_user_gets_the_same_nothing(self):
        """
        Tener cuenta en la plataforma no es tener nada que hacer en el panel,
        y tampoco da derecho a saber que existe.
        """
        self.verify_otp(self.make_user('cliente'))

        response = self.client.get(self.index)

        self.assertEqual(response.status_code, 404)

    def test_staff_without_the_second_factor_is_sent_to_set_it_up(self):
        """
        La excepcion deliberada.

        A quien ya sabe que el panel existe no se le esconde: esconderselo
        solo le haria perder la tarde buscando una averia que no hay. Se le
        manda a completar el segundo factor.
        """
        self.client.force_login(self.make_user('operador', staff=True))

        response = self.client.get(self.index)

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('two_factor:setup'), response['Location'])

    def test_staff_with_the_second_factor_gets_in(self):
        """Lo que si tiene que pasar: el panel sigue siendo usable."""
        self.verify_otp(self.make_user('operador', staff=True))

        response = self.client.get(self.index)

        self.assertEqual(response.status_code, 200)

    def test_a_deactivated_account_loses_the_panel(self):
        """
        Desactivar a alguien tiene que cerrarle la puerta aunque su sesion
        siguiera viva.
        """
        user = self.make_user('exempleado', staff=True)
        self.verify_otp(user)

        user.is_active = False
        user.save(update_fields=['is_active'])

        response = self.client.get(self.index)

        self.assertEqual(response.status_code, 404)


class AdminUrlIsNotTheControlTests(TestCase):
    """La URL secreta pasa a ser una molestia, no el control de acceso."""

    def test_knowing_the_url_is_no_longer_enough(self):
        """
        El resumen de todo el cambio: si mañana ``ADMIN_URL`` se filtra en un
        log, un historial o una captura, no se pierde el panel.
        """
        leaked = reverse('admin:index')

        response = self.client.get(leaked)

        self.assertEqual(response.status_code, 404)

    def test_a_registered_model_page_is_protected_too(self):
        """
        No basta con el indice: cada pagina de modelo pasa por ``admin_view``,
        y ahi es donde estaba la redireccion delatora.
        """
        url = reverse('admin:users_usermodel_changelist')

        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)


class AdminPermissionsStillApplyTests(TestCase):
    """Entrar por la puerta no reparte permisos."""

    def test_staff_without_model_permission_cannot_list_it(self):
        """
        La puerta decide quien pasa; los permisos de Django siguen decidiendo
        que ve cada quien una vez dentro.
        """
        user = UserModel.objects.create_user(
            username='auxiliar', email='aux@example.com',
            password=PASSWORD, is_staff=True,
        )
        user.user_permissions.add(
            Permission.objects.filter(codename='view_logentry').first()
        )

        login_with_otp(self.client, user)

        response = self.client.get(reverse('admin:users_usermodel_changelist'))

        self.assertIn(response.status_code, (403, 404))
