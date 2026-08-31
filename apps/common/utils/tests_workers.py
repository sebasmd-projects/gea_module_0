# apps/common/utils/tests_workers.py
"""
Que la respuesta sobre los workers sea la que dan los hechos.

Este comando existe para decidir algo caro --si merece la pena montar Celery--
y lo unico que lo hace util es que no adorne el resultado. Un «se puede» de mas
lleva a montar una cola que se muere sola en produccion, en silencio, con las
tareas que tuviera a medias.

Dos cosas se comprueban aqui.

**Que el Redis sirva de broker no se deduce de que sirva de cache.** La ACL de
``deploy/REDIS.md`` limita las claves a ``~gea:*`` y da ``+@read +@write
+@keyspace``. Un broker escribe claves con sus propios nombres, hace ping, usa
pub/sub y transacciones: nada de eso encaja, y sin embargo la cache va
perfecta. Verificado contra un Redis real con esa ACL, las cinco operaciones
responden NOPERM.

**Que un proceso sobreviva se mide, no se supone.** Cada desenlace --lo mataron
al instante, duro un rato, aguanto entero, sigue vivo-- lleva a una decision
distinta, asi que se comprueba que cada uno se cuente como lo que es.

    manage.py test apps.common.utils.tests_workers \\
        --settings=app_core.settings_test
"""

import tempfile
import time
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

GET_CONNECTION = 'django_redis.get_redis_connection'
POPEN = (
    'apps.common.utils.management.commands.check_workers.subprocess.Popen'
)


class Denied(Exception):
    """Lo que responde Redis cuando la ACL no deja: NOPERM."""


def cache_only_client():
    """
    Un Redis con la ACL de la cache: escribe en gea:* y nada mas.

    Reproduce lo que hace el servidor de verdad con
    ``~gea:* +@read +@write +@keyspace -@dangerous +flushdb``, que es la ACL
    que hay hoy en produccion.
    """
    client = mock.Mock()

    def set_(key, *args, **kwargs):
        if not str(key).startswith('gea:'):
            raise Denied('no permissions to access one of the keys')
        return True

    def refuse_key(key, *args, **kwargs):
        raise Denied('no permissions to access one of the keys')

    def refuse_command(*args, **kwargs):
        raise Denied('no permissions to run the command')

    client.set.side_effect = set_
    client.lpush.side_effect = refuse_key
    client.brpop.side_effect = refuse_key
    client.ping.side_effect = refuse_command
    client.publish.side_effect = refuse_command
    client.pipeline.side_effect = refuse_command

    return client


def open_client():
    """Un Redis que deja hacer de todo: el broker de otra base de datos."""
    client = mock.Mock()
    client.brpop.return_value = None
    return client


class WorkerCheckTestCase(SimpleTestCase):
    """Base: media propio y sin salir a ningun sitio."""

    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)

    def run_command(self, *, client=None, redis_url='redis://x', **options):
        out = StringIO()

        with override_settings(MEDIA_ROOT=self.media.name,
                               REDIS_URL=redis_url):
            with mock.patch(GET_CONNECTION,
                            return_value=client or cache_only_client()):
                call_command('check_workers', stdout=out, stderr=out,
                             no_color=True, **options)

        return out.getvalue()

    def write_beats(self, moments, *, name='20260830-120000.beats'):
        """Dejar el rastro de un proceso que latio en esos momentos."""
        target = Path(self.media.name) / 'worker_probe' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('\n'.join(str(moment) for moment in moments))

        return target


class TestBrokerIsNotTheCache(WorkerCheckTestCase):
    """
    Que el Redis vaya como cache no dice nada sobre el broker.

    Es el fallo mas traicionero de los cuatro: todo responde, la cache va, y
    las tareas desaparecerian sin ruido.
    """

    def test_the_cache_acl_is_reported_as_not_enough_for_a_broker(self):
        output = self.run_command()

        self.assertIn('NO como broker', output)
        self.assertIn('0 de 5', output)

    def test_each_denial_says_what_it_breaks(self):
        """
        Un NOPERM a secas no dice que arreglar. Cada uno lleva su motivo.
        """
        output = self.run_command()

        self.assertIn('~gea:*', output)          # las claves
        self.assertIn('@connection', output)     # el ping
        self.assertIn('@pubsub', output)         # los resultados
        self.assertIn('@transaction', output)    # no perder mensajes

    def test_ping_is_not_used_to_decide_whether_redis_answers(self):
        """
        La ACL de la cache no da @connection, asi que PING responde NOPERM con
        el servidor perfectamente vivo. Usarlo como prueba de conexion daria
        «no se pudo conectar» sobre un Redis que funciona.
        """
        output = self.run_command()

        self.assertNotIn('No se pudo conectar', output)
        self.assertIn('PING: DENEGADO', output)

    def test_an_open_broker_is_reported_as_usable(self):
        output = self.run_command(client=open_client())

        self.assertIn('sirve de broker tal como esta', output)

    def test_without_redis_there_is_no_broker(self):
        output = self.run_command(redis_url='')

        self.assertIn('No hay REDIS_URL', output)


class TestSurvivalIsTheOneThatDecides(WorkerCheckTestCase):
    """
    Cada desenlace lleva a una decision distinta, y hay que distinguirlos.
    """

    def test_with_nothing_launched_it_says_the_answer_is_missing(self):
        output = self.run_command()

        self.assertIn('Todavia no se ha lanzado ninguno', output)
        self.assertIn('Falta lo que decide', output)

    def test_killed_before_the_first_beat_is_a_flat_no(self):
        self.write_beats([])

        output = self.run_command()

        self.assertIn('lo mataron de inmediato', output)
        self.assertIn('NO sostiene un worker', output)

    def test_a_short_life_is_a_no_and_says_why_it_matters(self):
        """
        Sobrevivir un rato es peor que no arrancar: parece que funciona.
        """
        now = time.time()
        start = now - 40 * 60

        self.write_beats([start + n * 30 for n in range(2 * 4)])

        output = self.run_command()

        self.assertIn('Solo duro', output)
        self.assertIn('NO sostiene un worker', output)

    def test_dying_near_the_end_is_still_a_no(self):
        now = time.time()
        start = now - 60 * 60

        # Vivio 20 minutos de los 30: lo mataron, pero tarde.
        self.write_beats([start + n * 30 for n in range(41)])

        output = self.run_command()

        self.assertIn('lo mataron antes de acabar', output)
        self.assertIn('NO sostiene un worker', output)

    def test_surviving_the_whole_probe_is_a_yes_with_a_caveat(self):
        """
        Media hora no son semanas, y decir «se puede» sin ese matiz seria
        prometer de mas sobre la unica prueba que se pudo hacer.
        """
        now = time.time()
        start = now - 60 * 60

        self.write_beats([start + n * 30 for n in range(61)])

        output = self.run_command(client=open_client())

        self.assertIn('Aguanto la prueba entera', output)
        self.assertIn('puede sostener un worker', output)
        self.assertIn('no son semanas', output)

    def test_a_process_still_running_is_not_a_verdict_yet(self):
        now = time.time()

        self.write_beats([now - 60, now - 30, now])

        output = self.run_command()

        self.assertIn('Sigue vivo ahora mismo', output)
        self.assertIn('esta en marcha', output)

    def test_a_running_probe_is_not_confused_with_a_missing_one(self):
        """
        «No se ha lanzado» y «esta corriendo ahora» daban los dos el mismo
        resultado, asi que el comando pedia lanzar una prueba que ya estaba en
        marcha. Hacerle caso la habria reiniciado, perdiendo lo andado y
        dejando la respuesta igual de lejos.
        """
        now = time.time()

        self.write_beats([now - 120, now - 90, now - 60, now - 30, now])

        output = self.run_command()

        self.assertNotIn('--spawn', output)
        self.assertNotIn('Todavia no se ha lanzado', output)
        self.assertIn('No la relances', output)

    def test_a_running_probe_says_how_long_is_left(self):
        now = time.time()
        start = now - 10 * 60

        self.write_beats([start + n * 30 for n in range(21)])

        output = self.run_command()

        # 30 previstos menos los 10 que lleva.
        self.assertIn('20 minutos', output)

    def test_it_reads_the_last_probe(self):
        now = time.time()

        self.write_beats([now - 7200], name='20260101-000000.beats')
        self.write_beats([now - 60, now], name='20260830-120000.beats')

        output = self.run_command()

        self.assertIn('20260830-120000.beats', output)

    def test_surviving_does_not_hide_a_broker_that_is_not_ready(self):
        """
        Las dos condiciones son necesarias. Dar por bueno el conjunto porque
        una salio bien mandaria a montar una cola que no puede funcionar.
        """
        now = time.time()
        start = now - 60 * 60

        self.write_beats([start + n * 30 for n in range(61)])

        output = self.run_command()

        self.assertIn('todavia no sirve de broker', output)
        self.assertNotIn('puede sostener un worker', output)


class TestLaunchingTheProbe(WorkerCheckTestCase):
    """
    Lanzar es la mitad facil; lo que importa es que deje rastro.

    El proceso no se lanza de verdad: dura media hora, y una suite que deja
    procesos sueltos detras cada vez que corre es justo la clase de cosa que
    este comando existe para detectar.
    """

    def spawn(self, **options):
        with mock.patch(POPEN) as popen:
            output = self.run_command(spawn=True, **options)

        return output, popen

    def test_launching_detaches_the_process_from_the_request(self):
        """
        ``start_new_session`` es lo que lo saca del grupo de procesos de la
        peticion, que es lo que hace un worker y lo que el hosting mata. Sin
        eso la prueba mediria otra cosa.
        """
        output, popen = self.spawn()

        self.assertTrue(popen.called)
        self.assertTrue(popen.call_args.kwargs['start_new_session'])
        self.assertIn('Lanzado', output)

    def test_launching_promises_no_verdict(self):
        output, _ = self.spawn()

        self.assertIn('La conclusion sale al volver a ejecutarlo', output)
        self.assertNotIn('puede sostener un worker', output)

    def test_a_host_that_refuses_to_fork_is_already_an_answer(self):
        with mock.patch(POPEN, side_effect=OSError('no se permite')):
            output = self.run_command(spawn=True)

        self.assertIn('No se pudo lanzar', output)
        self.assertIn('no hay worker posible', output)

    def test_the_probe_directory_is_not_left_open_to_the_web(self):
        """Cuelga de MEDIA_ROOT, donde el servidor web sirve por defecto."""
        self.spawn()

        guard = Path(self.media.name) / 'worker_probe' / '.htaccess'

        self.assertTrue(guard.exists())
        self.assertIn('denied', guard.read_text())
