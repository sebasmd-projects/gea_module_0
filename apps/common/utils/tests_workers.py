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

FROM_URL = 'redis.Redis.from_url'
POPEN = (
    'apps.common.utils.management.commands.check_workers.subprocess.Popen'
)


class Denied(Exception):
    """Lo que responde Redis cuando la ACL no deja: NOPERM."""


def cache_only_client():
    """
    Un Redis con la ACL de la **cache**, al que se le pide hacer de broker.

    Reproduce lo que hace el servidor de verdad con
    ``~gea:* +@read +@write +@keyspace -@dangerous +flushdb``: las cinco
    operaciones del broker responden NOPERM. Es lo que sale si alguien apunta
    ``CELERY_BROKER_URL`` a las credenciales de la cache, que es el atajo
    tentador y el que no funciona.
    """
    client = mock.Mock()

    def refuse_key(key, *args, **kwargs):
        raise Denied('no permissions to access one of the keys')

    def refuse_command(*args, **kwargs):
        raise Denied('no permissions to run the command')

    client.lpush.side_effect = refuse_key
    client.brpop.side_effect = refuse_key
    client.get.side_effect = refuse_key
    client.ping.side_effect = refuse_command
    client.publish.side_effect = refuse_command
    client.pipeline.side_effect = refuse_command

    return client


def broker_client():
    """
    El usuario del broker bien puesto: lo suyo si, la cache no.

    ``~celery* ~_kombu* ~unacked* &* +@all -@dangerous -@admin``. Lo que
    distingue este de `wide_open_client` es la ultima linea: leer una clave de
    la cache responde NOPERM.
    """
    client = mock.Mock()
    client.brpop.return_value = None

    def refuse_cache_keys(key, *args, **kwargs):
        raise Denied('no permissions to access one of the keys')

    client.get.side_effect = refuse_cache_keys

    return client


def wide_open_client():
    """
    Un broker con ``~*``: funciona, y ademas alcanza las claves de la cache.

    Es el error que ya se cometio una vez -- dar ``~*`` y dar por hecho que la
    base de datos aparte separaba. No separa: las ACL de Redis no se acotan por
    base.
    """
    client = mock.Mock()
    client.brpop.return_value = None
    client.get.return_value = None

    return client


class WorkerCheckTestCase(SimpleTestCase):
    """Base: media propio y sin salir a ningun sitio."""

    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)

    def run_command(self, *, client=None, broker_url='redis://x/1', **options):
        out = StringIO()

        with override_settings(MEDIA_ROOT=self.media.name,
                               CELERY_BROKER_URL=broker_url):
            with mock.patch(FROM_URL,
                            return_value=client or broker_client()):
                call_command('check_workers', stdout=out, stderr=out,
                             no_color=True, **options)

        return out.getvalue()

    def write_beats(self, moments, *, name='20260830-120000.beats'):
        """Dejar el rastro de un proceso que latio en esos momentos."""
        target = Path(self.media.name) / 'worker_probe' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('\n'.join(str(moment) for moment in moments))

        return target


class TestAnUndeclaredLibraryIsNotAGreenTests(WorkerCheckTestCase):
    """
    Que `import celery` funcione no significa que este declarada.

    Es un verde que esconde un problema: si no esta en `requirements.txt`,
    esta porque alguien la instalo a mano en el servidor, y el proximo entorno
    que se levante desde ese fichero no la va a traer. La misma trampa que ya
    rompio produccion con `opentimestamps`, solo que del reves.
    """

    def run_with_celery(self, *, declared):
        fake = mock.Mock()
        fake.__version__ = '5.6.3'

        requirements = Path(self.media.name) / 'requirements.txt'
        requirements.write_text(
            'django==4.2\ncelery==5.6.3\n' if declared else 'django==4.2\n')

        out = StringIO()

        with override_settings(MEDIA_ROOT=self.media.name,
                               BASE_DIR=self.media.name,
                               CELERY_BROKER_URL='redis://x/1'):
            with mock.patch.dict('sys.modules', {'celery': fake}):
                with mock.patch(FROM_URL, return_value=broker_client()):
                    call_command('check_workers', stdout=out, stderr=out,
                                 no_color=True)

        return out.getvalue()

    def test_an_undeclared_library_is_flagged(self):
        output = self.run_with_celery(declared=False)

        self.assertIn('NO esta declarada en requirements.txt', output)

    def test_it_says_how_to_declare_it(self):
        output = self.run_with_celery(declared=False)

        self.assertIn('uv export --format=requirements-txt', output)

    def test_a_declared_library_says_nothing(self):
        output = self.run_with_celery(declared=True)

        self.assertIn('celery disponible', output)
        self.assertNotIn('NO esta declarada', output)


class TestBrokerIsNotTheCache(WorkerCheckTestCase):
    """
    Que el Redis vaya como cache no dice nada sobre el broker.

    Es el fallo mas traicionero de los cuatro: todo responde, la cache va, y
    las tareas desaparecerian sin ruido.
    """

    def test_a_working_broker_is_reported_as_usable(self):
        output = self.run_command()

        self.assertIn('sirve de broker', output)

    def test_the_cache_credentials_do_not_pass(self):
        """
        El atajo tentador: apuntar CELERY_BROKER_URL al usuario de la cache.
        Responde NOPERM a las cinco.
        """
        output = self.run_command(client=cache_only_client())

        self.assertIn('0 de 5', output)

    def test_each_denial_says_what_it_breaks(self):
        """Un NOPERM a secas no dice que arreglar. Cada uno lleva su motivo."""
        output = self.run_command(client=cache_only_client())

        self.assertIn('~celery*', output)        # las claves
        self.assertIn('@connection', output)     # el ping
        self.assertIn('@pubsub', output)         # los resultados
        self.assertIn('@transaction', output)    # no perder mensajes

    def test_without_a_broker_url_there_is_nothing_to_test_yet(self):
        """
        Y se dice asi, no como un fallo: mientras no haya cola, no hay nada
        roto. Lo que no puede hacer es callarse que el broker lleva
        credenciales propias.
        """
        output = self.run_command(broker_url='')

        self.assertIn('No hay CELERY_BROKER_URL', output)
        self.assertIn('CELERY_BROKER_URL=rediss://broker:', output)

    def test_it_does_not_test_the_broker_with_the_cache_connection(self):
        """
        La razon de ser de esta tanda.

        Antes se probaba con `get_redis_connection('default')` --el usuario de
        la cache, en la base 0--, asi que la comprobacion no podia dar verde ni
        con el broker perfectamente montado, y su propia conclusion mandaba a
        arreglar algo que ya estaba arreglado.
        """
        out = StringIO()

        with override_settings(MEDIA_ROOT=self.media.name,
                               CELERY_BROKER_URL='redis://x/1'):
            with mock.patch(FROM_URL, return_value=broker_client()):
                with mock.patch('django_redis.get_redis_connection') as cache:
                    call_command('check_workers', stdout=out, stderr=out,
                                 no_color=True)

        self.assertFalse(
            cache.called,
            'el broker no se prueba con la conexion de la cache',
        )


class TestUnreachableIsNotTheSameAsForbiddenTests(WorkerCheckTestCase):
    """
    «No llego» y «llegue y me dijeron que no» son diagnosticos distintos.

    Sin separarlos, un servidor apagado --o una CA mal puesta, o el
    cortafuegos-- salia como «0 de 5» con cinco explicaciones sobre permisos
    que faltan: cinco veces la respuesta equivocada, porque la ACL podia estar
    perfecta. Esa confusion es justo la que este comando existe para evitar.
    """

    def unreachable_client(self):
        import redis

        client = mock.Mock()
        client.ping.side_effect = redis.exceptions.ConnectionError(
            'Error 111 connecting to redis.example.com:6380')

        return client

    def bad_password_client(self):
        import redis

        client = mock.Mock()
        client.ping.side_effect = redis.exceptions.AuthenticationError(
            'WRONGPASS invalid username-password pair')

        return client

    def test_a_server_that_does_not_answer_is_not_blamed_on_the_acl(self):
        output = self.run_command(client=self.unreachable_client())

        self.assertIn('No se llega al servidor', output)
        self.assertIn('no dice nada de la ACL', output)

    def test_it_does_not_list_five_permission_problems(self):
        """Cinco explicaciones sobre la ACL cuando el problema es la red."""
        output = self.run_command(client=self.unreachable_client())

        self.assertNotIn('@pubsub', output)
        self.assertNotIn('0 de 5', output)

    def test_it_does_not_claim_the_cache_is_isolated_either(self):
        """
        Si no se llega al servidor, la prueba de aislamiento tampoco se ha
        hecho. Contarla como superada seria dar por bueno lo que no se ha
        podido mirar.
        """
        output = self.run_command(client=self.unreachable_client())

        self.assertNotIn('que es lo correcto', output)
        self.assertNotIn('no alcanza la cache', output)

    def test_a_wrong_password_says_it_is_the_password(self):
        output = self.run_command(client=self.bad_password_client())

        self.assertIn('No se pudo autenticar', output)
        self.assertIn('no son los de la cache', output)

    def test_a_noperm_on_ping_is_still_judged_as_an_acl_problem(self):
        """
        Un NOPERM sobre PING si es una respuesta del servidor: hay Redis
        delante y lo que falta es un permiso. Ese caso tiene que seguir
        contandose entre los cinco.
        """
        output = self.run_command(client=cache_only_client())

        self.assertIn('PING: DENEGADO', output)
        self.assertIn('0 de 5', output)


class TestTheBrokerDoesNotReachTheCache(WorkerCheckTestCase):
    """
    Que funcione no basta: tiene que no llegar a las claves de la cache.

    Es un error ya cometido. La primera version del documento daba ``~*`` al
    broker y daba por hecho que ponerlo en otra base de datos lo separaba de la
    cache. **Las ACL de Redis no se acotan por base de datos**, asi que ese
    usuario, conectado a la base 0, leia y borraba las claves ``gea:*`` -- entre
    ellas los contadores de intentos de acceso.
    """

    def test_a_broker_that_cannot_read_the_cache_passes(self):
        output = self.run_command(client=broker_client())

        self.assertIn('DENEGADO, que es lo correcto', output)
        self.assertIn('no alcanza la cache', output)

    def test_a_broker_that_reads_the_cache_is_not_good_enough(self):
        output = self.run_command(client=wide_open_client())

        self.assertIn('PERMITIDO', output)
        self.assertNotIn('no alcanza la cache', output)

    def test_it_says_that_another_database_does_not_fix_it(self):
        """
        Porque es justo la conclusion equivocada a la que se llega solo, y la
        que ya se escribio una vez en la documentacion.
        """
        output = self.run_command(client=wide_open_client())

        self.assertIn('no se acotan por base', output)


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

        output = self.run_command(client=broker_client())

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
        self.assertIn('NO la relances', output)

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

        output = self.run_command(broker_url='')

        self.assertIn('Falta el broker', output)
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


class TestTheProbeDuration(WorkerCheckTestCase):
    """
    Que la prueba larga se pueda pedir de verdad.

    Cuando la corta salia bien, el comando decia «dejalo corriendo un dia y
    vuelve a mirar» sin ofrecer manera de hacerlo: la duracion estaba fija en
    el codigo. Un consejo que quien lo lee no puede seguir es peor que no
    darlo, porque parece que falta algo por su parte.
    """

    def spawn(self, **options):
        with mock.patch(POPEN) as popen:
            output = self.run_command(spawn=True, **options)

        return output, popen

    def test_the_requested_duration_reaches_the_process(self):
        _, popen = self.spawn(minutes=120)

        script = popen.call_args.args[0][2]

        # 120 minutos a un latido cada 30 segundos.
        self.assertIn('range(240)', script)

    def test_the_duration_is_written_into_the_trace_name(self):
        """
        Al leer el rastro mas tarde hay que saber cuanto se esperaba, y puede
        no ser lo de por defecto. Sin esto, una prueba de un dia que muriera a
        la media hora se leeria como «aguanto entera».
        """
        _, popen = self.spawn(minutes=1440)

        path = popen.call_args.args[0][3]

        self.assertTrue(path.endswith('-1440m.beats'), path)

    def test_an_absurd_duration_is_brought_back_to_something_measurable(self):
        _, popen = self.spawn(minutes=1)

        script = popen.call_args.args[0][2]

        # Cinco minutos es el minimo: por debajo no se mide nada.
        self.assertIn('range(10)', script)

    def test_a_long_probe_is_read_against_its_own_duration(self):
        now = time.time()
        # El ultimo latido, hace rato: si fuera reciente se leeria como «sigue
        # vivo» y no como «lo mataron».
        start = now - 90 * 60

        # Una prueba de un dia que solo vivio 40 minutos NO aguanto entera.
        self.write_beats(
            [start + n * 30 for n in range(81)],
            name='20260830-120000-1440m.beats',
        )

        output = self.run_command()

        self.assertIn('lo mataron antes de acabar', output)
        self.assertNotIn('Aguanto la prueba entera', output)

    def test_a_short_probe_that_survives_asks_for_the_long_one(self):
        now = time.time()
        start = now - 60 * 60

        self.write_beats(
            [start + n * 30 for n in range(61)],
            name='20260830-120000-30m.beats',
        )

        output = self.run_command(client=broker_client())

        self.assertIn('Aguanto la prueba entera', output)
        self.assertIn('--minutes 1440', output)

    def test_a_long_probe_that_survives_does_not_ask_for_more(self):
        now = time.time()
        start = now - 25 * 60 * 60

        self.write_beats(
            [start + n * 60 for n in range(1441)],
            name='20260830-120000-1440m.beats',
        )

        output = self.run_command(client=broker_client())

        self.assertIn('Aguanto la prueba entera', output)
        self.assertNotIn('--minutes 1440', output)
