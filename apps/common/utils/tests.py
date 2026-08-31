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

from .blocking import (MAX_BLOCK, MAX_STORED_PATHS, block_duration,
                       block_until, capped_until, note_attempt)
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


class ExponentialBlockTests(TestCase):
    """
    La curva del castigo.

    Habia dos politicas para lo mismo -- la vista multiplicaba por el numero
    de intentos, el middleware sumaba un intervalo fijo -- asi que el mismo
    escaner recibia castigos distintos segun por donde entrara. Y las dos
    crecian demasiado despacio para lo que hace un bot.
    """

    base = timedelta(minutes=15)

    def test_the_first_attempt_costs_the_base(self):
        self.assertEqual(block_duration(1, self.base), self.base)

    def test_each_attempt_doubles_the_previous_one(self):
        for attempt in range(1, 7):
            self.assertEqual(
                block_duration(attempt + 1, self.base),
                block_duration(attempt, self.base) * 2,
                f'attempt {attempt + 1} should double attempt {attempt}',
            )

    def test_it_grows_faster_than_multiplying_by_the_attempt_count(self):
        """
        Lo que hacia antes la vista trampa.

        Multiplicar sale barato justo al principio, que es cuando conviene
        que salga caro: al quinto intento eran 75 minutos.
        """
        linear = self.base * 5

        self.assertGreater(block_duration(5, self.base), linear)

    def test_it_never_goes_past_the_ceiling(self):
        self.assertEqual(block_duration(500, self.base), MAX_BLOCK)

    def test_a_huge_attempt_count_does_not_cost_cpu(self):
        """
        ``2 ** 40000`` es tiempo de CPU regalado al que ataca.

        Con el techo el resultado seria el mismo, pero calcularlo no.
        """
        self.assertEqual(block_duration(10 ** 6, self.base), MAX_BLOCK)

    def test_the_deadline_never_goes_past_the_ceiling(self):
        until = block_until(999, self.base)

        self.assertLessEqual(until, timezone.now() + MAX_BLOCK)

    def test_a_block_is_never_shortened(self):
        """
        Bajar la duracion a mitad de un bloqueo seria premiar la insistencia.
        """
        current = timezone.now() + timedelta(hours=8)

        self.assertGreaterEqual(block_until(1, self.base, current=current),
                                current)

    def test_the_view_and_the_middleware_agree(self):
        """
        La razon de que la curva viva en un solo sitio.

        Con la politica escrita dos veces, la duracion del bloqueo dependia de
        por donde hubiera entrado la peticion.
        """
        from .middleware.block_suspicious_request import \
            DetectSuspiciousRequestMiddleware
        from .views import HttpRequestAttackView

        middleware = DetectSuspiciousRequestMiddleware(lambda request: None)

        self.assertEqual(
            middleware.block_base,
            HttpRequestAttackView.time_in_minutes,
        )


class BlockedRequestTests(TestCase):
    """El middleware, de punta a punta."""

    def blocked_response(self):
        IPBlockedModel.objects.create(
            current_ip=SCANNER,
            reason=IPBlockedModel.ReasonsChoices.SERVER_HTTP_REQUEST,
            blocked_until=timezone.now() + timedelta(minutes=30),
            session_info={'attempt_count': 7, 'paths': []},
        )

        return self.client.get('/wp-admin/', REMOTE_ADDR=SCANNER)

    def test_a_blocked_ip_gets_404_not_403(self):
        """
        Un 403 confirma; un 404 no dice nada.

        Es la misma regla que ya sigue el admin (invariante 7). El 403 que
        habia aqui le decia al escaner que existe un bloqueo por IP y que su
        sonda habia dado en la trampa.
        """
        self.assertEqual(self.blocked_response().status_code, 404)

    def test_the_response_does_not_mention_the_block(self):
        body = self.blocked_response().content.decode()

        for leak in ('blocked', 'Blocked', 'suspicious', 'Suspicious'):
            self.assertNotIn(leak, body, f'the response leaks {leak!r}')

    def test_the_response_does_not_reveal_the_attempt_count(self):
        """
        Decia cuantos intentos llevaba y cuando caducaba el bloqueo: justo lo
        que un escaner necesita para saber cuando volver.
        """
        response = self.blocked_response()

        self.assertNotIn('attempt_count', response.context or {})
        self.assertNotIn('blocked_until', response.context or {})

    def test_it_looks_like_any_other_missing_page(self):
        """
        Si el bloqueo tuviera su propia pagina, distinguirlas seria trivial.
        """
        blocked = self.blocked_response().content

        IPBlockedModel.objects.all().delete()
        plain = self.client.get(
            '/una-ruta-que-no-existe/', REMOTE_ADDR=VICTIM
        )

        self.assertEqual(plain.status_code, 404)
        self.assertEqual(blocked, plain.content)

    def test_whitelisting_actually_unblocks(self):
        """El remedio documentado tiene que surtir efecto de verdad."""
        IPBlockedModel.objects.create(
            current_ip=SCANNER,
            reason=IPBlockedModel.ReasonsChoices.SERVER_HTTP_REQUEST,
            blocked_until=timezone.now() + timedelta(minutes=30),
            session_info={'attempt_count': 1, 'paths': []},
        )
        WhiteListedIPModel.objects.create(current_ip=SCANNER)

        response = self.client.get('/health/', REMOTE_ADDR=SCANNER)

        self.assertEqual(response.status_code, 200)

    def test_an_expired_block_lets_the_request_through(self):
        IPBlockedModel.objects.create(
            current_ip=SCANNER,
            reason=IPBlockedModel.ReasonsChoices.SERVER_HTTP_REQUEST,
            blocked_until=timezone.now() - timedelta(minutes=1),
            session_info={'attempt_count': 1, 'paths': []},
        )

        response = self.client.get('/health/', REMOTE_ADDR=SCANNER)

        self.assertEqual(response.status_code, 200)

    def test_the_block_escalates_when_the_ip_insists(self):
        entry = IPBlockedModel.objects.create(
            current_ip=SCANNER,
            reason=IPBlockedModel.ReasonsChoices.SERVER_HTTP_REQUEST,
            blocked_until=timezone.now() + timedelta(minutes=1),
            session_info={'attempt_count': 6, 'paths': []},
        )

        self.client.get('/wp-admin/', REMOTE_ADDR=SCANNER)

        entry.refresh_from_db()

        self.assertEqual(entry.session_info['attempt_count'], 7)
        # Siete intentos son horas, no el minuto que quedaba.
        self.assertGreater(
            entry.blocked_until, timezone.now() + timedelta(hours=1)
        )

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
