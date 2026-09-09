# apps/common/utils/tests/test_scanning.py
"""
Las dos senales nuevas de la capa inicial.

Hasta ahora solo habia una: la trampa de ``attack_patterns``, que salta con
los terminos escritos en ``COMMON_ATTACK_TERMS``. Es precisa --por eso puede
permitirse bloquear al primer intento-- y por lo mismo es ciega ante todo lo
que nadie anticipo. Ampliar esa lista no es la salida: cada termino nuevo es
una ruta legitima menos, y ya hubo un autobloqueo por meter ``env``.

Se anaden dos que no dependen de acertar el nombre de la ruta:

1. **Rafagas de 404 sobre rutas distintas.** No mira *que* se pide sino
   *como*. Un diccionario pide decenas de sitios que no existen y casi nunca
   repite; una persona que se equivoca de URL genera uno o dos y recarga.
2. **Herramientas que se identifican solas** en el ``User-Agent``. Nadie
   ejecuta sqlmap por error.

Lo que se fija aqui es sobre todo **lo que NO tiene que bloquear**, que es la
mitad que cuesta cara: un falso positivo aqui deja fuera a alguien de verdad.

    manage.py test apps.common.utils.tests.test_scanning \\
        --settings=app_core.settings_test
"""

from unittest import mock

from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from .. import scanning
from ..middleware.block_bots import BlockBadBotsMiddleware
from ..models import IPBlockedModel, WhiteListedIPModel

IP = '203.0.113.5'


def a_request(path='/loquesea', agent='Mozilla/5.0'):
    request = RequestFactory().get(path, REMOTE_ADDR=IP)
    request.META['HTTP_USER_AGENT'] = agent
    request.user = mock.Mock(is_authenticated=False)

    return request


class ScanningWindowTests(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def hit(self, path):
        return scanning.note_not_found(a_request(path), path)

    def test_a_lost_user_is_not_a_scanner(self):
        """
        Dos o tres URL mal escritas en una tarde. Es el caso mas comun de 404
        y no puede costar un bloqueo.
        """
        for path in ('/contacot', '/contacto/', '/nosotros'):
            state = self.hit(path)

        self.assertFalse(scanning.looks_like_enumeration(state))

    def test_reloading_the_same_broken_link_is_not_a_scan(self):
        """
        El falso positivo mas probable: un enlace roto en un correo que se
        reenvia a media oficina, o alguien dandole a F5. Volumen alto, un solo
        sitio. Sin la condicion de dispersion, esto bloquearia.
        """
        for _ in range(scanning.threshold() * 2):
            state = self.hit('/enlace-roto-de-un-correo')

        self.assertGreater(state['count'], scanning.threshold())
        self.assertFalse(scanning.looks_like_enumeration(state))

    def test_a_dictionary_is_a_scan(self):
        for number in range(scanning.threshold() + 5):
            state = self.hit(f'/admin-backup-{number}')

        self.assertTrue(scanning.looks_like_enumeration(state))

    def test_below_the_threshold_nothing_happens(self):
        """Aunque todas las rutas sean distintas: hace falta volumen."""
        for number in range(scanning.threshold() - 1):
            state = self.hit(f'/ruta-{number}')

        self.assertFalse(scanning.looks_like_enumeration(state))

    def test_the_window_is_forgotten_when_asked(self):
        for number in range(5):
            self.hit(f'/ruta-{number}')

        scanning.forget(a_request())

        self.assertEqual(self.hit('/otra')['count'], 1)


class WithoutCacheNothingIsBlockedTests(SimpleTestCase):
    """
    Falla **abierto**, y aqui si.

    Esto decide un bloqueo, no un permiso. Con la cache caida, fallar cerrado
    seria empezar a bloquear a cualquiera que reciba un 404 por una averia que
    no es suya. El coste de fallar abierto es que durante el corte no se
    detecta enumeracion -- o sea, la situacion de antes de que esto existiera.
    """

    def test_a_dead_cache_does_not_decide(self):
        with mock.patch.object(scanning.cache, 'get', return_value=None), \
                mock.patch.object(scanning.cache, 'set', return_value=None):
            state = scanning.note_not_found(a_request(), '/x')

        self.assertTrue(state['degraded'])
        self.assertFalse(scanning.looks_like_enumeration(state))

    def test_a_cache_that_raises_does_not_decide_either(self):
        with mock.patch.object(scanning.cache, 'get', side_effect=RuntimeError):
            state = scanning.note_not_found(a_request(), '/x')

        self.assertTrue(state['degraded'])


class ScannerSignatureTests(TestCase):
    """
    Un escaner que anuncia su nombre es la senal mas limpia que hay. Y la
    respuesta importa: confirmarle el bloqueo le dice que hay filtro por
    agente, y cambiar la cadena cuesta un parametro.
    """

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.middleware = BlockBadBotsMiddleware(lambda request: mock.Mock(
            status_code=200))

    def test_a_declared_scanner_gets_the_silent_404(self):
        response = self.middleware(a_request(agent='sqlmap/1.8#stable'))

        self.assertEqual(response.status_code, 404)

    def test_the_answer_does_not_say_it_was_blocked(self):
        """La misma regla del invariante 20: un 403 confirma; un 404 no."""
        response = self.middleware(a_request(agent='nikto/2.5.0'))
        body = response.content.decode().lower()

        self.assertNotIn('bot blocked', body)
        self.assertNotIn('forbidden', body)

    def test_it_opens_a_block(self):
        self.middleware(a_request(agent='sqlmap/1.8'))

        entry = IPBlockedModel.objects.get(current_ip=IP)

        self.assertEqual(
            entry.reason, IPBlockedModel.ReasonsChoices.SCANNER_SIGNATURE)
        self.assertEqual(entry.matched_pattern, 'sqlmap')

    def test_a_policy_crawler_still_gets_a_plain_403(self):
        """
        No es lo mismo. Un rastreador que respeta las reglas necesita entender
        que la respuesta es deliberada para dejar de volver; un 404 seria
        mentira y le haria reintentar.
        """
        response = self.middleware(a_request(agent='Mozilla/5.0 (compatible; GPTBot/1.2)'))

        self.assertEqual(response.status_code, 403)
        self.assertFalse(IPBlockedModel.objects.exists())

    def test_a_normal_browser_passes(self):
        response = self.middleware(a_request(
            agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'))

        self.assertEqual(response.status_code, 200)

    def test_the_name_is_matched_as_a_token(self):
        """
        Como subcadena suelta, `nmap` cae dentro de cualquier palabra que lo
        contenga. Es exactamente asi como `env` acabo bloqueando `/envio/`.
        """
        response = self.middleware(a_request(agent='Enmapador/2.0'))

        self.assertEqual(response.status_code, 200)

    def test_a_whitelisted_address_is_left_alone(self):
        """El remedio documentado del proyecto tiene que servir tambien aqui."""
        WhiteListedIPModel.objects.create(current_ip=IP, reason='pruebas')

        response = self.middleware(a_request(agent='sqlmap/1.8'))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(IPBlockedModel.objects.exists())

    @override_settings(IP_BLOCKED_TIME_IN_MINUTES=15)
    def test_insisting_costs_more(self):
        for _ in range(3):
            self.middleware(a_request(agent='nuclei/3.1'))

        entry = IPBlockedModel.objects.get(current_ip=IP)

        self.assertEqual(entry.attempt_count, 3)
