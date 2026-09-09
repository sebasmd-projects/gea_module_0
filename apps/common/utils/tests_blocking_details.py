# apps/common/utils/tests_blocking_details.py
"""
Que una fila de bloqueo se pueda leer sin abrirla.

La tabla guardaba todo dentro de ``session_info``, un JSON. Servia para
guardar y para nada mas: no se podia ordenar por intentos, ni filtrar las que
vienen de un proveedor cloud, ni saber si un bloqueo seguia en pie. Para
contestar «¿esto es un escaner o alguien que se equivoco de URL?» habia que
abrir la fila y leer un JSON a mano.

Lo que se fija aqui:

* que las columnas **se derivan del JSON**, y no cuentan una cosa distinta;
* que «rutas unicas» separa de verdad a quien recarga de quien enumera;
* que el estado del bloqueo **se calcula al leerlo**, no se guarda;
* que la duracion se dice en palabras y baja hasta los segundos;
* y que el origen de la IP se resuelve sin salir a la red.

    manage.py test apps.common.utils.tests_blocking_details \\
        --settings=app_core.settings_test
"""

from datetime import timedelta

from django.test import RequestFactory, SimpleTestCase, TestCase
from django.utils import timezone

from .blocking import (apply_to_entry, block_duration, describe_duration,
                       note_attempt)
from .models import IPBlockedModel


def a_request(path='/wp-login.php', agent='curl/8.4.0'):
    request = RequestFactory().get(path, REMOTE_ADDR='203.0.113.5')
    request.META['HTTP_USER_AGENT'] = agent

    return request


class TheColumnsComeFromTheJsonTests(TestCase):
    """
    Son datos duplicados a proposito, y esa duplicacion solo se sostiene si
    la escribe una sola funcion. Con dos, la tabla acabaria diciendo cuatro
    intentos donde el JSON dice nueve, y entonces no se puede creer ninguno.
    """

    def test_the_attempt_count_matches_the_trail(self):
        entry = IPBlockedModel(current_ip='203.0.113.5')
        info = {}

        for _ in range(4):
            info = note_attempt(info, a_request())

        apply_to_entry(entry, info, a_request())

        self.assertEqual(entry.attempt_count, 4)
        self.assertEqual(entry.attempt_count, info['attempt_count'])

    def test_unique_paths_counts_places_not_visits(self):
        """
        Lo que separa a una persona de un diccionario. Recargar veinte veces
        el mismo enlace roto es un usuario molesto; veinte rutas distintas es
        un escaneo, y la diferencia no esta en el total.
        """
        entry = IPBlockedModel(current_ip='203.0.113.5')
        info = {}

        for _ in range(5):
            info = note_attempt(info, a_request('/misma-ruta'))

        apply_to_entry(entry, info, a_request('/misma-ruta'))

        self.assertEqual(entry.attempt_count, 5)
        self.assertEqual(entry.unique_paths, 1)

    def test_many_places_show_up_as_many(self):
        entry = IPBlockedModel(current_ip='203.0.113.5')
        info = {}

        for number in range(5):
            info = note_attempt(info, a_request(f'/ruta-{number}'))

        apply_to_entry(entry, info, a_request('/ruta-9'))

        self.assertEqual(entry.unique_paths, 5)

    def test_the_first_detection_does_not_move(self):
        """
        `created` cambia si alguien guarda la fila desde el admin. La primera
        deteccion es de la actividad de la IP y solo la mueve un intento suyo.
        """
        entry = IPBlockedModel.objects.create(current_ip='203.0.113.5')
        apply_to_entry(entry, {'attempt_count': 1}, a_request())
        entry.save()

        first = entry.first_seen

        apply_to_entry(entry, {'attempt_count': 2}, a_request())
        entry.save()

        self.assertEqual(entry.first_seen, first)
        self.assertGreaterEqual(entry.last_seen, first)

    def test_the_agent_is_kept(self):
        entry = IPBlockedModel(current_ip='203.0.113.5')

        apply_to_entry(entry, {}, a_request(agent='sqlmap/1.8'))

        self.assertEqual(entry.user_agent, 'sqlmap/1.8')

    def test_a_very_long_agent_does_not_break_the_column(self):
        """Quien ataca elige su cabecera; el ancho de la columna no."""
        entry = IPBlockedModel(current_ip='203.0.113.5')

        apply_to_entry(entry, {}, a_request(agent='x' * 900))

        self.assertEqual(len(entry.user_agent), 500)


class TheBlockStateIsCalculatedNotStoredTests(TestCase):
    """
    `is_active` decia «bloqueada» para siempre: nadie la baja cuando el reloj
    pasa. La tabla ensenaba como activos bloqueos caducados hacia meses.
    """

    def test_a_live_block_reads_as_blocked(self):
        entry = IPBlockedModel(
            current_ip='203.0.113.5',
            blocked_until=timezone.now() + timedelta(minutes=30),
        )

        self.assertTrue(entry.is_currently_blocked)

    def test_an_expired_block_stops_reading_as_blocked_by_itself(self):
        """Sin cron y sin que nadie toque la fila: lo dice el reloj."""
        entry = IPBlockedModel(
            current_ip='203.0.113.5',
            blocked_until=timezone.now() - timedelta(seconds=1),
        )

        self.assertTrue(entry.is_active)
        self.assertFalse(entry.is_currently_blocked)

    def test_switching_it_off_by_hand_wins(self):
        entry = IPBlockedModel(
            current_ip='203.0.113.5',
            is_active=False,
            blocked_until=timezone.now() + timedelta(hours=5),
        )

        self.assertFalse(entry.is_currently_blocked)

    def test_time_remaining_is_none_when_there_is_none(self):
        entry = IPBlockedModel(
            current_ip='203.0.113.5',
            blocked_until=timezone.now() - timedelta(minutes=1),
        )

        self.assertIsNone(entry.time_remaining)


class TheDurationIsSaidInWordsTests(SimpleTestCase):
    """
    `timesince` de Django corta en dos unidades y no baja de los minutos, asi
    que un bloqueo de cuarenta segundos salia como «0 minutos» -- justo cuando
    alguien esta mirando la tabla para ver si ya puede entrar.
    """

    def test_seconds_are_said(self):
        self.assertEqual(
            describe_duration(timedelta(seconds=40), spanish=True),
            '40 segundos',
        )

    def test_it_goes_up_to_years(self):
        said = describe_duration(timedelta(days=800), spanish=True)

        self.assertIn('año', said)

    def test_it_stops_at_three_units(self):
        said = describe_duration(
            timedelta(days=400, hours=5, minutes=3, seconds=9), spanish=True)

        self.assertEqual(len(said.split(' ')) // 2, 3)

    def test_nothing_left_is_zero_seconds(self):
        self.assertEqual(
            describe_duration(timedelta(seconds=-5), spanish=True),
            '0 segundos',
        )

    def test_it_can_speak_english(self):
        self.assertEqual(
            describe_duration(timedelta(hours=2), spanish=False),
            '2 hours',
        )

    def test_the_curve_and_the_words_agree(self):
        """
        El admin ensena la duracion del proximo bloqueo. Si la funcion que la
        dice y la que la calcula se separaran, la tabla prometeria un castigo
        distinto del que aplica.
        """
        base = timedelta(minutes=15)

        self.assertEqual(
            describe_duration(block_duration(3, base), spanish=True),
            '1 hora',
        )


class TheOriginIsResolvedOfflineTests(TestCase):
    """
    Varias de las IP que caen en la trampa pertenecen a rangos de proveedores
    cloud, y eso ya es una senal: una persona navega desde una IP residencial
    o de oficina; un servidor no navega.

    Se resuelve con una tabla que viaja en el repositorio. Nada de consultar a
    un servicio de reputacion: seria una llamada de red dentro de **cada**
    peticion, con `ATOMIC_REQUESTS` puesto, y de paso le contaria a un tercero
    quien visita el sitio.
    """

    def test_a_cloud_address_is_labelled(self):
        entry = IPBlockedModel.objects.create(current_ip='3.15.20.30')

        self.assertTrue(entry.is_datacenter)
        self.assertEqual(entry.network_owner, 'Amazon AWS')

    def test_an_address_outside_the_table_is_not_called_residential(self):
        """
        No saber no es lo mismo que saber que no. La tabla cubre a los
        proveedores desde los que llega el escaneo, no a todo internet.
        """
        entry = IPBlockedModel.objects.create(current_ip='203.0.113.5')

        self.assertFalse(entry.is_datacenter)
        self.assertEqual(entry.network_owner, '')

    def test_the_most_specific_prefix_wins(self):
        """
        Con solapamientos, quedarse con el primero daria el dueno segun como
        este ordenada la tabla, que es la clase de error que nadie mira.
        """
        from .netintel import _compiled_networks

        lengths = [network.prefixlen for network, _owner in _compiled_networks()]

        self.assertEqual(lengths, sorted(lengths, reverse=True))

    def test_a_broken_address_does_not_raise(self):
        entry = IPBlockedModel.objects.create(current_ip='no-es-una-ip')

        self.assertFalse(entry.is_datacenter)

    def test_a_row_made_by_hand_also_gets_its_origin(self):
        """
        Las filas se crean por cuatro sitios distintos, y una fila sin origen
        es justo la que no se puede leer.
        """
        entry = IPBlockedModel(current_ip='45.55.1.1')
        entry.save()

        self.assertEqual(entry.network_owner, 'DigitalOcean')
