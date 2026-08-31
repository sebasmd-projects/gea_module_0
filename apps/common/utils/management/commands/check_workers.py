# apps/common/utils/management/commands/check_workers.py
"""
Si este servidor puede sostener un worker (Celery o cualquier otro).

La pregunta de fondo es si se pueden sacar de la peticion los trabajos que hoy
la bloquean: la traduccion por OpenAI dentro de una senal ``pre_save``, la
generacion de PDF, el envio de correo, el anclaje. Con ``ATOMIC_REQUESTS`` cada
uno de esos segundos se paga con una transaccion abierta.

Un worker no es una libreria que se instala: es **un proceso que vive fuera de
la peticion y no se muere**. Y eso, en un hosting compartido, no se decide
leyendo documentacion sino probandolo, porque depende de limites que el
proveedor no publica. De ahi este comando: no propone nada, mide.

Cuatro cosas, y las cuatro tienen que salir bien:

1. **Que la libreria este.** La mas facil, y la unica que se arregla con pip.
2. **Que el Redis sirva de broker.** Que sirva de cache no basta: un broker
   necesita otras claves y otros comandos, y la ACL actual esta escrita para
   la cache. Es el fallo que mas despista, porque el Redis «funciona».
3. **Que quepan mas procesos.** Un worker ocupa sitio en un limite compartido
   con los procesos que atienden la web.
4. **Que un proceso desprendido sobreviva.** La de verdad. Muchos hostings
   compartidos matan lo que no sea una peticion web, y no lo avisan: el worker
   arranca, funciona un rato y desaparece.

La cuarta necesita dos ejecuciones separadas en el tiempo, porque la pregunta
es literalmente «sigue vivo un rato despues»:

    manage.py check_workers            # mira 1, 2 y 3, y lee la prueba anterior
    manage.py check_workers --spawn    # lanza el proceso de prueba
    # ... media hora despues ...
    manage.py check_workers            # dice cuanto sobrevivio
"""

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

PROBE_DIR = 'worker_probe'

# Cada cuanto late el proceso de prueba, y cuanto aguanta como mucho. Media
# hora es de sobra: lo que mata a un proceso desprendido lo mata en minutos.
PROBE_BEAT_SECONDS = 30
PROBE_MAX_MINUTES = 30

# Un worker de verdad vive semanas. Sobrevivir a esto no lo garantiza, pero no
# sobrevivir lo descarta, que es lo que se quiere saber.
PROBE_GOOD_MINUTES = 10

# Estados de la prueba de supervivencia. Son tres y no dos: «no se ha lanzado»
# y «esta corriendo ahora» no son lo mismo, y confundirlos hacia que el
# comando pidiera lanzar una prueba que ya estaba en marcha -- lo que ademas
# habria reiniciado la medicion.
NOT_LAUNCHED = 'not_launched'
RUNNING = 'running'

# Lo que un broker de Celery necesita del Redis y la cache no. Cada entrada es
# (etiqueta, funcion, para que sirve) y se prueba de verdad contra el servidor.
BROKER_KEY = 'celery'
KOMBU_KEY = '_kombu.binding.celery'


class Command(BaseCommand):
    help = 'Comprueba si este servidor puede sostener un worker en segundo plano.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--spawn',
            action='store_true',
            help=(
                'Lanza un proceso de prueba desprendido de la peticion. No '
                'hace nada salvo escribir la hora cada 30 segundos durante '
                'media hora. Vuelve a ejecutar el comando mas tarde para ver '
                'cuanto sobrevivio.'
            ),
        )

    def handle(self, *args, **options):
        verdict = {}

        verdict['celery'] = self._check_celery()
        verdict['broker'] = self._check_broker()
        verdict['limits'] = self._check_limits()

        if options['spawn']:
            self._spawn_probe()
        else:
            verdict['survival'] = self._read_probe()

        self._conclude(verdict, spawned=options['spawn'])

        return None

    # ------------------------------------------------------------------
    def _section(self, title):
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING(title))

    def _check_celery(self):
        """
        Que la libreria este. Es lo unico de aqui que arregla un pip install.

        Que falte no significa nada malo: todavia no se ha decidido usarla.
        """
        self._section('1. Libreria')

        try:
            import celery
        except ImportError:
            self.stdout.write(
                '   celery no esta instalado. Es lo esperable si aun no se ha '
                'decidido usarlo, y es lo unico de esta lista que se arregla '
                'con pip. Lo que decide no es esto.'
            )
            return None

        self.stdout.write(self.style.SUCCESS(
            f'   celery disponible ({celery.__version__}).'
        ))

        return True

    # ------------------------------------------------------------------
    def _redis_client(self):
        """
        Conexion cruda al Redis, sin la capa de cache.

        Hay que saltarse la cache a proposito: ``django-redis`` prefija las
        claves con ``gea:`` y se traga los errores con ``IGNORE_EXCEPTIONS``,
        que es justo lo que aqui hay que ver. Un broker escribe claves con sus
        propios nombres y sin prefijo.
        """
        from django_redis import get_redis_connection

        return get_redis_connection('default')

    def _try(self, label, operation, explains):
        """Ejecutar una operacion del broker y contar que dijo el servidor."""
        try:
            operation()
        except Exception as error:  # noqa: BLE001
            self.stdout.write(self.style.ERROR(
                f'   {label}: DENEGADO ({type(error).__name__}: {error})'
            ))
            self.stdout.write(f'      {explains}')
            return False

        self.stdout.write(self.style.SUCCESS(f'   {label}: permitido'))

        return True

    def _check_broker(self):
        """
        Que el Redis valga de broker, que no es lo mismo que valer de cache.

        La ACL de ``deploy/REDIS.md`` esta escrita para la cache: limita las
        claves a ``~gea:*`` y da ``+@read +@write +@keyspace``. Un broker de
        Celery escribe claves con **sus** nombres (``celery``,
        ``_kombu.binding.*``, ``unacked``), usa **pub/sub** para los resultados
        y **transacciones** para no perder mensajes. Nada de eso encaja.

        El sintoma es de los peores: el Redis responde, la cache va, y las
        tareas desaparecen sin ruido. Por eso se prueba comando a comando en
        vez de dar por hecho que «Redis funciona».
        """
        self._section('2. Redis como broker (no como cache)')

        if not getattr(settings, 'REDIS_URL', ''):
            self.stdout.write(
                '   No hay REDIS_URL. Sin Redis no hay broker; mira '
                'deploy/REDIS.md.'
            )
            return False

        # Ojo con usar PING para saber si hay conexion: la ACL de la cache no
        # da @connection, asi que PING responde NOPERM aunque el servidor este
        # perfectamente. Se comprueba escribiendo una clave de las suyas, que
        # es lo que la cache hace de verdad.
        try:
            client = self._redis_client()
            client.set('gea:worker-probe', b'1', ex=30)
        except Exception as error:  # noqa: BLE001
            self.stdout.write(self.style.ERROR(
                f'   No se pudo conectar: {type(error).__name__}: {error}'
            ))
            self.stdout.write(
                '   Comprueba primero la cache con "manage.py check_cache".'
            )
            return False

        probe = f'{BROKER_KEY}.probe.{uuid.uuid4().hex[:8]}'

        checks = [
            (
                'Escribir fuera de gea:*',
                lambda: client.lpush(probe, b'x'),
                'La ACL limita las claves a ~gea:*, y un broker usa las suyas. '
                'Hay que anadir sus patrones al usuario, o darle un usuario y '
                'una base de datos aparte.',
            ),
            (
                'PING',
                lambda: client.ping(),
                'La ACL de la cache no da @connection. La cache nunca hace '
                'ping, pero un broker lo usa para saber si el servidor sigue '
                'ahi.',
            ),
            (
                'Cola de mensajes (LPUSH/BRPOP)',
                lambda: client.brpop(probe, timeout=1),
                'Es como se reparte el trabajo entre workers. Sin esto no hay '
                'cola.',
            ),
            (
                'Pub/sub (PUBLISH)',
                lambda: client.publish(f'{probe}.channel', b'x'),
                'Celery lo usa para los resultados y para hablar con los '
                'workers. La ACL de la cache no da @pubsub.',
            ),
            (
                'Transacciones (MULTI/EXEC)',
                lambda: client.pipeline(transaction=True).llen(
                    probe).execute(),
                'Es lo que evita perder un mensaje a medio repartir. La ACL '
                'de la cache no da @transaction.',
            ),
        ]

        allowed = 0

        for label, operation, explains in checks:
            if self._try(label, operation, explains):
                allowed += 1

        try:
            client.delete(probe)
        except Exception:  # noqa: BLE001
            pass

        if allowed == len(checks):
            self.stdout.write(self.style.SUCCESS(
                '   El Redis sirve de broker tal como esta.'
            ))
            return True

        self.stdout.write(self.style.WARNING(
            f'   {allowed} de {len(checks)}. El Redis funciona como cache '
            'pero NO como broker: la ACL esta escrita para la cache. Se abre '
            'sin tocar la cache dandole al broker su propio usuario y su '
            'propia base de datos (ver deploy/REDIS.md).'
        ))

        return False

    # ------------------------------------------------------------------
    def _check_limits(self):
        """
        Cuantos procesos deja tener el hosting, y cuantos hay ya.

        Un worker no es gratis: ocupa una plaza del mismo limite que los
        procesos que atienden la web. En un hosting compartido ese limite suele
        ser estrecho, y gastarlo en un worker puede significar que una visita
        se quede sin proceso.
        """
        self._section('3. Sitio para otro proceso')

        try:
            import resource

            soft, hard = resource.getrlimit(resource.RLIMIT_NPROC)
        except Exception:  # noqa: BLE001
            soft = hard = None

        if soft is None:
            self.stdout.write('   No se pudo leer el limite de procesos.')
        elif soft == resource.RLIM_INFINITY:
            self.stdout.write(
                '   Sin limite declarado de procesos para este usuario.'
            )
        else:
            self.stdout.write(f'   Limite de procesos: {soft} (tope {hard})')

        running = self._count_own_processes()

        if running is not None:
            self.stdout.write(f'   Procesos ahora mismo de este usuario: {running}')

            if soft not in (None, getattr(resource, 'RLIM_INFINITY', -1)):
                free = soft - running

                if free < 5:
                    self.stdout.write(self.style.WARNING(
                        f'   Quedan {free} plazas. Un worker ocupa al menos '
                        'una, y las mismas plazas atienden la web: si se '
                        'agotan, las visitas se quedan sin proceso.'
                    ))
                else:
                    self.stdout.write(f'   Quedan unas {free} plazas libres.')

        # CloudLinux (lo que usa casi todo cPanel compartido) limita ademas
        # por LVE, y ese limite no sale en getrlimit.
        if Path('/proc/lve').exists() or Path('/usr/sbin/lvectl').exists():
            self.stdout.write(self.style.WARNING(
                '   Este servidor usa CloudLinux/LVE. Ahi el limite de '
                'procesos y de memoria lo pone el proveedor por cuenta, no se '
                've con getrlimit, y suele matar lo que se pase. Es el motivo '
                'mas comun de que un worker desaparezca solo.'
            ))

        return True

    def _count_own_processes(self):
        """Procesos de este usuario, leidos de /proc para no depender de ps."""
        uid = os.getuid()
        count = 0

        try:
            for entry in Path('/proc').iterdir():
                if not entry.name.isdigit():
                    continue

                try:
                    if entry.stat().st_uid == uid:
                        count += 1
                except OSError:
                    continue
        except OSError:
            return None

        return count

    # ------------------------------------------------------------------
    def _probe_dir(self) -> Path:
        return Path(settings.MEDIA_ROOT) / PROBE_DIR

    def _protect(self, directory: Path):
        """Cerrar al web el directorio, que cuelga de MEDIA_ROOT."""
        guard = directory / '.htaccess'

        if guard.exists():
            return

        source = Path(settings.BASE_DIR) / 'deploy' / 'media-protected.htaccess'

        try:
            guard.write_bytes(source.read_bytes())
        except OSError:
            pass

    def _spawn_probe(self):
        """
        Lanzar un proceso desprendido que solo late.

        Se desprende de verdad (``start_new_session``): sale del grupo de
        procesos de la peticion, que es lo que hace un worker. Si el hosting
        mata lo que no sea web, esto es lo que se va a morir, y ese es
        justamente el dato.
        """
        self._section('4. Proceso en segundo plano')

        directory = self._probe_dir()

        try:
            directory.mkdir(parents=True, exist_ok=True)
            self._protect(directory)
        except OSError as error:
            self.stdout.write(self.style.ERROR(
                f'   No se pudo crear {directory}: {error}'
            ))
            return

        beats = directory / f'{timezone.now():%Y%m%d-%H%M%S}.beats'

        script = (
            'import time,sys\n'
            'path=sys.argv[1]\n'
            f'for i in range({int(PROBE_MAX_MINUTES * 60 / PROBE_BEAT_SECONDS)}):\n'
            '    open(path,"a").write(str(time.time())+"\\n")\n'
            f'    time.sleep({PROBE_BEAT_SECONDS})\n'
        )

        try:
            with open(os.devnull, 'wb') as quiet:
                subprocess.Popen(
                    [sys.executable, '-c', script, str(beats)],
                    stdout=quiet, stderr=quiet, stdin=subprocess.DEVNULL,
                    start_new_session=True,
                    cwd=str(settings.BASE_DIR),
                )
        except Exception as error:  # noqa: BLE001
            self.stdout.write(self.style.ERROR(
                f'   No se pudo lanzar: {type(error).__name__}: {error}'
            ))
            self.stdout.write(
                '   Si el hosting no deja crear procesos, no hay worker '
                'posible aqui. Es una respuesta, aunque sea la mala.'
            )
            return

        self.stdout.write(self.style.SUCCESS(
            '   Lanzado. Late cada '
            f'{PROBE_BEAT_SECONDS}s durante {PROBE_MAX_MINUTES} minutos.'
        ))
        self.stdout.write(f'   Deja su rastro en {beats.name}')
        self.stdout.write('')
        self.stdout.write(
            f'   Vuelve dentro de {PROBE_MAX_MINUTES} minutos y ejecuta el '
            'comando sin marcar nada. Lo que interesa no es que arranque '
            '--eso ya se ve--, sino que siga vivo entonces.'
        )

    def _read_probe(self):
        """
        Leer el rastro del ultimo proceso de prueba y decir cuanto duro.

        Un worker de verdad vive semanas. Sobrevivir a esta prueba no lo
        garantiza; no sobrevivir lo descarta, que es lo que se puede saber en
        media hora.
        """
        self._section('4. Proceso en segundo plano')

        try:
            traces = sorted(self._probe_dir().glob('*.beats'))
        except OSError:
            traces = []

        if not traces:
            self.stdout.write(
                '   Todavia no se ha lanzado ninguno. Lanza uno con --spawn y '
                'vuelve dentro de media hora: es la comprobacion que decide.'
            )
            return NOT_LAUNCHED

        trace = traces[-1]

        try:
            beats = [
                float(line) for line in
                trace.read_text().split() if line.strip()
            ]
        except (OSError, ValueError):
            self.stdout.write(self.style.ERROR(
                f'   No se pudo leer {trace.name}.'
            ))
            return NOT_LAUNCHED

        if not beats:
            self.stdout.write(self.style.ERROR(
                '   El proceso se lanzo y no llego a escribir ni una vez: lo '
                'mataron de inmediato. No hay worker posible aqui.'
            ))
            return False

        lived = (beats[-1] - beats[0]) / 60
        since = (time.time() - beats[-1]) / 60
        expected = PROBE_MAX_MINUTES
        alive = since < 2

        self.stdout.write(
            f'   {len(beats)} latidos en {trace.name}: '
            + (
                f'lleva {lived:.0f} minutos vivo de los {expected} previstos.'
                if alive else
                f'vivio {lived:.0f} minutos de los {expected} previstos.'
            )
        )

        if alive:
            remaining = max(0, expected - lived)

            self.stdout.write(self.style.SUCCESS(
                '   Sigue vivo ahora mismo, que ya es buena senal.'
            ))
            self.stdout.write(
                f'   Vuelve dentro de {remaining:.0f} minutos, cuando la '
                'prueba haya terminado. **No la relances**: lanzar otra '
                'empezaria a contar de cero y perderia lo andado.'
            )
            return RUNNING

        if lived >= expected - 1:
            self.stdout.write(self.style.SUCCESS(
                '   Aguanto la prueba entera. Este servidor deja vivir a un '
                'proceso desprendido.'
            ))
            self.stdout.write(
                '   Ojo: media hora no son semanas. Antes de fiarlo todo a un '
                'worker aqui, dejalo corriendo un dia y vuelve a mirar.'
            )
            return True

        if lived >= PROBE_GOOD_MINUTES:
            self.stdout.write(self.style.WARNING(
                f'   Duro {lived:.0f} minutos y lo mataron antes de acabar. '
                'Un worker aqui se moriria solo cada tanto, en silencio, y con '
                'el las tareas que tuviera a medias.'
            ))
            return False

        self.stdout.write(self.style.ERROR(
            f'   Solo duro {lived:.0f} minutos. Este hosting no deja procesos '
            'en segundo plano: un worker aqui no se sostiene.'
        ))

        return False

    # ------------------------------------------------------------------
    def _conclude(self, verdict, *, spawned):
        """Juntar las cuatro respuestas en una sola, sin adornarla."""
        self.stdout.write('')

        if spawned:
            self.stdout.write(
                'Prueba lanzada. La conclusion sale al volver a ejecutarlo.'
            )
            return

        survival = verdict.get('survival')

        if survival == NOT_LAUNCHED:
            self.stdout.write(
                'Falta lo que decide: que un proceso desprendido sobreviva. '
                'Lanzalo con --spawn.'
            )
            return

        if survival == RUNNING:
            self.stdout.write(
                'La prueba que decide esta en marcha. Vuelve cuando termine y '
                'ejecuta esto otra vez sin marcar nada.'
            )

            if not verdict.get('broker'):
                self.stdout.write(
                    'Mientras tanto hay algo que si se puede ir haciendo: el '
                    'Redis todavia no sirve de broker, y eso se arregla en la '
                    'ACL sin tocar la cache.'
                )

            return

        if not survival:
            self.stdout.write(self.style.ERROR(
                'Este servidor NO sostiene un worker.'
            ))
            self.stdout.write(
                'No es un problema de configuracion ni de libreria: el hosting '
                'mata los procesos que no atienden peticiones. Las salidas son '
                'poner el worker en otra maquina --el VPS donde ya corre el '
                'Redis-- o seguir con cron, que aqui si funciona.'
            )
            return

        if not verdict.get('broker'):
            self.stdout.write(self.style.WARNING(
                'El servidor sostiene un proceso, pero el Redis todavia no '
                'sirve de broker. Es lo siguiente que hay que arreglar, y se '
                'arregla en la ACL sin tocar la cache.'
            ))
            return

        self.stdout.write(self.style.SUCCESS(
            'Este servidor puede sostener un worker.'
        ))
        self.stdout.write(
            'Con una advertencia: media hora de prueba no son semanas de '
            'produccion. Dejalo corriendo un dia antes de fiarle trabajo que '
            'importe.'
        )
