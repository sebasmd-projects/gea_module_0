# apps/common/utils/tests_throttling.py
"""
Los cupos, y sobre todo que pasa con ellos cuando la cache no responde.

El fallo que origina este fichero no se veia de ninguna manera. Los contadores
vivian en cache, la cache va con ``IGNORE_EXCEPTIONS`` a proposito, y eso
--esta es la parte contraintuitiva-- **no lanza la excepcion, devuelve
``None``**. Asi que:

    cache.get(clave) or 0   ->   0
    0 < limite              ->   True, pasa

Ni excepcion, ni log, ni sintoma. Con Redis caido, la unica superficie no
autenticada de la plataforma se quedaba sin ningun freno y nadie se enteraba.

Por eso la simulacion de averia de estas pruebas es ``incr`` devolviendo
``None`` y no ``incr`` lanzando: lanzar es lo que **no** hace en produccion, y
una prueba que simulara una excepcion habria pasado en verde sobre el codigo
roto.

    manage.py test apps.common.utils.tests_throttling \\
        --settings=app_core.settings_test
"""

from unittest.mock import patch

from django.core.cache import cache
from django.test import RequestFactory, TestCase

from .throttling import RateLimit


def dead_cache():
    """
    Redis caido, tal y como se ve desde `django-redis` con IGNORE_EXCEPTIONS.

    `add` no guarda nada y `incr` devuelve `None` en lugar de reventar. Es
    exactamente lo que hace `omit_exception`.
    """
    return patch.multiple(
        'apps.common.utils.throttling.cache',
        add=lambda *a, **k: False,
        incr=lambda *a, **k: None,
    )


class ThrottleMixin:

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

        self.factory = RequestFactory()

    def request(self, ip='203.0.113.7'):
        return self.factory.get('/', REMOTE_ADDR=ip)


class TestTheCounterCounts(ThrottleMixin, TestCase):
    """Lo basico, con la cache viva."""

    def test_it_allows_exactly_the_limit(self):
        limit = RateLimit('demo', limit=3, window=60)
        request = self.request()

        for _ in range(3):
            self.assertTrue(limit.consume(request))

        self.assertFalse(limit.consume(request))

    def test_each_address_has_its_own_bucket(self):
        limit = RateLimit('demo', limit=2, window=60)

        for _ in range(3):
            limit.consume(self.request(ip='203.0.113.7'))

        self.assertTrue(limit.consume(self.request(ip='198.51.100.9')))

    def test_two_limits_do_not_share_a_bucket(self):
        one = RateLimit('uno', limit=1, window=60)
        other = RateLimit('otro', limit=1, window=60)
        request = self.request()

        self.assertTrue(one.consume(request))
        self.assertTrue(other.consume(request))


class TestTheScope(ThrottleMixin, TestCase):
    """
    Cuando el cupo no es de quien pide sino de quien recibe.

    Es la diferencia entre limitar los correos que salen de una IP y limitar
    los que entran en un buzon. Lo segundo tiene que ignorar la IP: quien
    manda la elige, quien recibe no.
    """

    def test_the_scope_replaces_the_address(self):
        limit = RateLimit('correo', limit=2, window=60)

        for _ in range(2):
            limit.consume(self.request(ip='203.0.113.7'), scope='ana@x.com')

        self.assertFalse(
            limit.consume(self.request(ip='198.51.100.9'), scope='ana@x.com'),
            'cambiar de IP no puede rellenar el cupo de un buzon',
        )

    def test_a_different_scope_keeps_its_own(self):
        limit = RateLimit('correo', limit=1, window=60)

        limit.consume(self.request(), scope='ana@x.com')

        self.assertTrue(limit.consume(self.request(), scope='beto@x.com'))

    def test_the_scope_is_normalised(self):
        """Nadie teclea su correo dos veces igual."""
        limit = RateLimit('correo', limit=1, window=60)

        limit.consume(self.request(), scope='Ana@X.com')

        self.assertFalse(limit.consume(self.request(), scope='  ana@x.com '))

    def test_the_scope_is_not_stored_in_the_clear(self):
        """
        Una llave de cache es un sitio donde nadie espera datos personales, y
        aqui el `scope` suele ser un correo o un numero de documento. Quedan
        en Redis, salen en un `KEYS *` y sobreviven al proceso.
        """
        limit = RateLimit('correo', limit=1, window=60)

        key = limit.key_for(self.request(), scope='ana@x.com')

        self.assertNotIn('ana@x.com', key)
        self.assertNotIn('ana', key)


class TestWhatHappensWhenTheCacheIsDown(ThrottleMixin, TestCase):
    """
    El fallo que da nombre a este fichero.
    """

    def test_a_closed_limit_refuses(self):
        limit = RateLimit('codigos', limit=5, window=60)

        with dead_cache():
            self.assertFalse(limit.consume(self.request()))

    def test_it_refuses_from_the_very_first_attempt(self):
        """
        No es "se agota antes": es que sin contador no hay limite que aplicar,
        y este limite **es** el control. Dejar pasar el primero ya seria dejar
        pasar todos, porque todos son el primero.
        """
        limit = RateLimit('codigos', limit=5, window=60)

        with dead_cache():
            self.assertFalse(limit.consume(self.request()))
            self.assertFalse(limit.consume(self.request()))

    def test_an_open_limit_allows(self):
        limit = RateLimit(
            'peticion', limit=5, window=60,
            fail_open=True, reason='ejercer un derecho no puede depender de Redis',
        )

        with dead_cache():
            self.assertTrue(limit.consume(self.request()))

    def test_the_outage_is_logged_as_an_error_either_way(self):
        """
        Una defensa degradada tiene que salir en cualquier revision del log,
        tanto si se corta como si se deja pasar. Aviso no: error.
        """
        closed = RateLimit('codigos', limit=5, window=60)
        opened = RateLimit(
            'peticion', limit=5, window=60,
            fail_open=True, reason='motivo escrito',
        )

        with dead_cache():
            with self.assertLogs('apps.common.utils.throttling', 'ERROR'):
                closed.consume(self.request())

            with self.assertLogs('apps.common.utils.throttling', 'ERROR'):
                opened.consume(self.request())

    def test_recovering_the_cache_recovers_the_limit(self):
        limit = RateLimit('codigos', limit=2, window=60)

        with dead_cache():
            limit.consume(self.request())

        self.assertTrue(limit.consume(self.request()))


class TestFailOpenNeedsAReason(ThrottleMixin, TestCase):
    """
    Que haya que escribir el motivo no es burocracia.

    Un `fail_open=True` suelto no se distingue de un descuido seis meses
    despues, y la decision de dejar pasar durante una averia es justo la que
    hay que poder revisar: depende de que impide el limite, no del limite.
    """

    def test_it_refuses_to_be_built_without_one(self):
        with self.assertRaises(ValueError):
            RateLimit('demo', limit=1, window=60, fail_open=True)

    def test_with_a_reason_it_builds(self):
        limit = RateLimit(
            'demo', limit=1, window=60,
            fail_open=True, reason='la molestia se acaba con la averia',
        )

        self.assertTrue(limit.fail_open)

    def test_closed_is_the_default(self):
        self.assertFalse(RateLimit('demo', limit=1, window=60).fail_open)


class TestTheKeyExpiringMidWayIsNotAnOutage(ThrottleMixin, TestCase):
    """
    La carrera que hay entre el `add` y el `incr`.

    Si la ventana vence justo ahi, `incr` lanza `ValueError` --la clave no
    existe-- y eso **no** es una averia: es el caso normal de una ventana que
    acaba de expirar. Confundirlo con un Redis caido cortaria el servicio a
    quien llega en el peor microsegundo.
    """

    def test_it_counts_as_the_first_attempt(self):
        limit = RateLimit('demo', limit=3, window=60)

        with patch.multiple(
            'apps.common.utils.throttling.cache',
            add=lambda *a, **k: True,
            incr=self._expired,
        ):
            self.assertTrue(limit.consume(self.request()))

    @staticmethod
    def _expired(*args, **kwargs):
        raise ValueError('key not found')
