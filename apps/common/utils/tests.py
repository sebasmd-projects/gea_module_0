# apps/common/utils/tests.py
"""
Mitigacion anti-escaneo: que estorbe a los bots sin dejar fuera a nadie.

Es mitigacion de ruido, no seguridad, asi que el criterio es *fallar abierto*.
Cada prueba de ``BlockingSafetyTests`` reproduce una forma concreta de dejar
fuera a quien no toca; todas fallaban antes.

    manage.py test apps.common.utils --settings=app_core.settings_test
"""

from datetime import timedelta

from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from apps.project.common.users.models import UserModel

from .blocking import MAX_BLOCK, MAX_STORED_PATHS, capped_until, note_attempt
from .client_ip import get_client_ip, is_exempt
from .models import IPBlockedModel, WhiteListedIPModel

PASSWORD = 'pw-for-tests-123'
VICTIM = '203.0.113.9'
SCANNER = '198.51.100.7'


class ClientIpTests(TestCase):
    """De donde viene una peticion, sin creerse lo que el cliente cuenta."""

    def setUp(self):
        self.factory = RequestFactory()

    def test_by_default_the_forwarded_header_is_not_believed(self):
        """
        Es la diferencia entre poder bloquear a otro y no poder.

        ``X-Forwarded-For`` lo pone el cliente. Si se le cree sin haber un
        proxy propio delante, basta con mandarlo con la IP de la victima para
        que el bloqueo caiga sobre ella.
        """
        request = self.factory.get(
            '/', HTTP_X_FORWARDED_FOR=VICTIM, REMOTE_ADDR=SCANNER
        )

        self.assertEqual(get_client_ip(request), SCANNER)

    @override_settings(TRUSTED_PROXY_DEPTH=1)
    def test_with_a_declared_proxy_the_header_is_used(self):
        """Un salto: la IP buena es la ultima, que la puso nuestro proxy."""
        request = self.factory.get(
            '/',
            HTTP_X_FORWARDED_FOR=f'{VICTIM}, {SCANNER}',
            REMOTE_ADDR='10.0.0.1',
        )

        self.assertEqual(get_client_ip(request), SCANNER)

    @override_settings(TRUSTED_PROXY_DEPTH=1)
    def test_a_malformed_header_falls_back_instead_of_breaking(self):
        request = self.factory.get(
            '/', HTTP_X_FORWARDED_FOR='not-an-ip', REMOTE_ADDR=SCANNER
        )

        self.assertEqual(get_client_ip(request), SCANNER)

    def test_an_unusable_address_does_not_raise(self):
        request = self.factory.get('/', REMOTE_ADDR='')

        self.assertEqual(get_client_ip(request), '0.0.0.0')


class ExemptionTests(TestCase):
    """Quien no debe quedarse fuera, no se queda fuera."""

    @classmethod
    def setUpTestData(cls):
        cls.staff = UserModel.objects.create_user(
            username='mitig_staff', email='staff@example.com',
            password=PASSWORD, user_type=UserModel.UserTypeChoices.BUYER,
            is_staff=True,
        )
        cls.plain = UserModel.objects.create_user(
            username='mitig_plain', email='plain@example.com',
            password=PASSWORD, user_type=UserModel.UserTypeChoices.BUYER,
        )

    def setUp(self):
        self.factory = RequestFactory()

    def request_from(self, ip, user=None):
        request = self.factory.get('/whatever/', REMOTE_ADDR=ip)
        request.user = user or self._anonymous()
        return request

    @staticmethod
    def _anonymous():
        from django.contrib.auth.models import AnonymousUser
        return AnonymousUser()

    def test_a_whitelisted_ip_is_exempt(self):
        """
        Era el remedio documentado del proyecto, y no funcionaba.

        La lista blanca la miraba la vista que crea el bloqueo, pero no el
        middleware que lo aplica, que es quien decide si te deja pasar.
        """
        request = self.request_from(SCANNER)
        self.assertFalse(is_exempt(request))

        WhiteListedIPModel.objects.create(current_ip=SCANNER)

        self.assertTrue(is_exempt(self.request_from(SCANNER)))

    def test_authenticated_staff_is_exempt(self):
        """Un administrador no puede quedarse fuera por teclear mal una URL."""
        self.assertTrue(is_exempt(self.request_from(SCANNER, self.staff)))

    def test_an_ordinary_user_is_not_exempt(self):
        self.assertFalse(is_exempt(self.request_from(SCANNER, self.plain)))


class BlockingSafetyTests(TestCase):
    """El castigo crece con la insistencia, pero no sin fin."""

    def setUp(self):
        self.factory = RequestFactory()

    def test_a_block_never_grows_past_the_ceiling(self):
        """
        Sin techo, insistir lo volvia perpetuo.

        Cada peticion sumaba otro intervalo, asi que un bot a diez peticiones
        por segundo -- o un usuario legitimo recargando -- acababa con un
        bloqueo que no se soltaba nunca.
        """
        until = timezone.now() + timedelta(days=400)

        for _ in range(200):
            until = capped_until(timedelta(minutes=15), current=until)

        self.assertLessEqual(until, timezone.now() + MAX_BLOCK)

    def test_extending_moves_the_deadline_forward(self):
        first = capped_until(timedelta(minutes=15))
        second = capped_until(timedelta(minutes=15), current=first)

        self.assertGreater(second, first)

    def test_the_recorded_paths_do_not_grow_without_limit(self):
        """Un bot insistente podia inflar el JSON de la fila hasta MB."""
        info = {}

        for index in range(MAX_STORED_PATHS * 4):
            request = self.factory.get(f'/wp-admin/{index}/')
            info = note_attempt(info, request)

        self.assertEqual(len(info['paths']), MAX_STORED_PATHS)
        # Se conservan las ultimas, que son las que sirven para diagnosticar.
        self.assertIn('/wp-admin/199/', info['paths'])
        self.assertEqual(info['attempt_count'], MAX_STORED_PATHS * 4)

    def test_note_attempt_does_not_mutate_what_it_receives(self):
        original = {'attempt_count': 1, 'paths': ['/a/']}
        note_attempt(original, self.factory.get('/b/'))

        self.assertEqual(original, {'attempt_count': 1, 'paths': ['/a/']})


class BlockedRequestTests(TestCase):
    """El middleware, de punta a punta."""

    def test_a_blocked_ip_gets_403(self):
        IPBlockedModel.objects.create(
            current_ip=SCANNER,
            reason=IPBlockedModel.ReasonsChoices.SERVER_HTTP_REQUEST,
            blocked_until=timezone.now() + timedelta(minutes=30),
            session_info={'attempt_count': 1, 'paths': []},
        )

        response = self.client.get('/wp-admin/', REMOTE_ADDR=SCANNER)

        self.assertEqual(response.status_code, 403)

    def test_whitelisting_actually_unblocks(self):
        """El remedio documentado tiene que surtir efecto de verdad."""
        IPBlockedModel.objects.create(
            current_ip=SCANNER,
            reason=IPBlockedModel.ReasonsChoices.SERVER_HTTP_REQUEST,
            blocked_until=timezone.now() + timedelta(minutes=30),
            session_info={'attempt_count': 1, 'paths': []},
        )
        WhiteListedIPModel.objects.create(current_ip=SCANNER)

        response = self.client.get('/wp-admin/', REMOTE_ADDR=SCANNER)

        self.assertNotEqual(response.status_code, 403)

    def test_an_expired_block_lets_the_request_through(self):
        IPBlockedModel.objects.create(
            current_ip=SCANNER,
            reason=IPBlockedModel.ReasonsChoices.SERVER_HTTP_REQUEST,
            blocked_until=timezone.now() - timedelta(minutes=1),
            session_info={'attempt_count': 1, 'paths': []},
        )

        response = self.client.get('/wp-admin/', REMOTE_ADDR=SCANNER)

        self.assertNotEqual(response.status_code, 403)

    def test_a_forged_header_does_not_get_someone_else_blocked(self):
        """
        El ataque completo: bloquear a un tercero desde fuera.

        Con la cabecera creida a ciegas, pedir una ruta trampa diciendo ser la
        victima dejaba a la victima bloqueada.
        """
        self.client.get(
            '/wp-admin/setup-config.php',
            REMOTE_ADDR=SCANNER,
            HTTP_X_FORWARDED_FOR=VICTIM,
        )

        self.assertFalse(
            IPBlockedModel.objects.filter(current_ip=VICTIM).exists(),
            'a forged header must never get a third party blocked',
        )
