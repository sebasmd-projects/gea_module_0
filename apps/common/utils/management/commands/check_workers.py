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
   necesita otras claves y otros comandos, y la ACL de la cache esta escrita
   para la cache. Es el fallo que mas despista, porque el Redis «funciona».
   Se prueba con las credenciales **del broker** (``CELERY_BROKER_URL``), no
   con las de la cache: probarlo con las de la cache no mide si el Redis
   serviria de broker, mide que el usuario de la cache no vale para eso -- que
   ya se sabe, y que no cambia por mucho que se arregle la ACL.
3. **Que quepan mas procesos.** Un worker ocupa sitio en un limite compartido
   con los procesos que atienden la web.
4. **Que un proceso desprendido sobreviva.** La de verdad. Muchos hostings
   compartidos matan lo que no sea una peticion web, y no lo avisan: el worker
   arranca, funciona un rato y desaparece.

La cuarta necesita dos ejecuciones separadas en el tiempo, porque la pregunta
es literalmente «sigue vivo un rato despues»:

    manage.py check_workers            # mira 1, 2 y 3, y lee la prueba anterior
    manage.py check_workers --spawn    # lanza el proceso de prueba (media hora)
    # ... media hora despues ...
    manage.py check_workers            # dice cuanto sobrevivio

Media hora descarta el hosting que mata todo enseguida, que es lo mas comun.
No dice nada del que mata un proceso de vez en cuando, y eso solo se ve
dejandolo mas tiempo:

    manage.py check_workers --spawn --minutes 1440    # un dia
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

# Margen de la duracion pedida. Por debajo de cinco minutos no se mide nada
# util; por encima de una semana el rastro crece sin que aporte mas.
PROBE_MIN_MINUTES = 5
PROBE_LIMIT_MINUTES = 7 * 24 * 60

# La prueba larga que se sugiere cuando la corta sale bien: un dia entero, que
# es donde ya se notan los reinicios y los recortes del proveedor.
PROBE_LONG_MINUTES = 24 * 60

# El nombre con el que empiezan las claves de prueba del broker. Tiene que
# empezar por «celery» para caer dentro de `~celery*`, que es uno de los tres
# patrones que se le conceden: una prueba con otro nombre estaria midiendo un
# permiso que el broker de verdad no necesita.
BROKER_KEY = 'celery'


class Command(BaseCommand):
    help = 'Comprueba si este servidor puede sostener un worker en segundo plano.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--spawn',
            action='store_true',
            help=(
                'Lanza un proceso de prueba desprendido de la peticion. No '
                'hace nada salvo escribir la hora cada 30 segundos. Vuelve a '
                'ejecutar el comando mas tarde para ver cuanto sobrevivio.'
            ),
        )
        parser.add_argument(
            '--minutes',
            type=int,
            default=PROBE_MAX_MINUTES,
            help=(
                'Cuanto debe durar la prueba. Media hora descarta el hosting '
                'que mata todo enseguida, que es lo mas comun, pero no prueba '
                'que un worker aguante una semana. Para eso hace falta dejarlo '
                'un dia: --minutes 1440.'
            ),
        )

    def handle(self, *args, **options):
        verdict = {}

        verdict['celery'] = self._check_celery()
        verdict['broker'] = self._check_broker()
        verdict['limits'] = self._check_limits()

        if options['spawn']:
            self._spawn_probe(self._requested_minutes(options))
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

        if not self._is_declared('celery'):
            # Un verde que esconde un problema. Que la libreria importe aqui
            # solo dice que **hoy** esta en este entorno; si no esta declarada,
            # esta porque alguien la instalo a mano, y el proximo entorno que
            # se levante desde `requirements.txt` no la va a traer. Es la misma
            # trampa que ya rompio produccion con `opentimestamps`, del reves.
            self.stdout.write(self.style.WARNING(
                '   Pero NO esta declarada en requirements.txt: esta instalada '
                'a mano. Produccion instala con pip desde ese fichero, asi que '
                'el dia que se rehaga el entorno la cola se queda sin libreria.'
            ))
            self.stdout.write(
                '      Se arregla declarandola y reexportando:'
            )
            self.stdout.write(
                '         uv add celery && uv export --format=requirements-txt '
                '> requirements.txt'
            )

        return True

    def _is_declared(self, package: str) -> bool:
        """
        Si el paquete esta en ``requirements.txt``, que es lo que instala
        produccion.

        Se mira ese fichero y no ``pyproject.toml`` porque es el que manda en
        el servidor: en cPanel no hay `uv`. Si no se puede leer, se calla --un
        aviso que no se puede fundamentar es ruido.
        """
        target = Path(settings.BASE_DIR) / 'requirements.txt'

        try:
            declared = target.read_text(encoding='utf-8').lower()
        except OSError:
            return True

        return any(
            line.split('==')[0].split('[')[0].strip() == package
            for line in declared.splitlines()
            if line.strip() and not line.lstrip().startswith('#')
        )

    # ------------------------------------------------------------------
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

    def _broker_client(self):
        """
        Conexion con las credenciales **del broker**, que no son las de la cache.

        Es la diferencia que hace util a esta comprobacion. Probar el broker
        con el usuario de la cache no mide si el Redis serviria de broker: mide
        que el usuario de la cache no sirve para eso, que ya se sabe de
        antemano y no cambia por mucho que se arregle la ACL. Con esa conexion
        la comprobacion no podia dar verde nunca, ni con el broker perfectamente
        montado, y su propia conclusion mandaba a arreglar algo que ya estaba
        arreglado.
        """
        import redis

        return redis.Redis.from_url(
            settings.CELERY_BROKER_URL,
            socket_connect_timeout=5,
            socket_timeout=5,
        )

    def _broker_answers(self, client) -> bool:
        """
        Que al otro lado haya un Redis que conteste, antes de juzgar la ACL.

        Sin esta separacion, un servidor apagado --o una CA mal puesta, o el
        cortafuegos-- salia como «0 de 5» con cinco explicaciones sobre
        permisos que faltan. Cinco veces la respuesta equivocada: la ACL puede
        estar perfecta y el problema ser que no se llega. Esa confusion es
        justo la que este comando existe para evitar.

        La distincion la da el tipo de error. Un NOPERM llega como
        ``ResponseError`` --el servidor contesto, y contesto que no-- mientras
        que un servidor inalcanzable llega como ``ConnectionError`` o
        ``TimeoutError``, que no son respuestas suyas.
        """
        import redis

        try:
            client.ping()
        except redis.exceptions.AuthenticationError as error:
            self.stdout.write(self.style.ERROR(
                f'   No se pudo autenticar: {error}'
            ))
            self.stdout.write(
                '      El usuario o la contrasena de CELERY_BROKER_URL no son '
                'los del usuario «broker» de redis.conf. Ojo: no son los de la '
                'cache, son otros.'
            )
            return False
        except (redis.exceptions.ConnectionError,
                redis.exceptions.TimeoutError) as error:
            self.stdout.write(self.style.ERROR(
                f'   No se llega al servidor: {type(error).__name__}: {error}'
            ))
            self.stdout.write(
                '      Esto no dice nada de la ACL, que puede estar perfecta. '
                'Mira el host y el puerto de CELERY_BROKER_URL, la ruta de la '
                'CA y la regla del cortafuegos (deploy/REDIS.md, paso 5).'
            )
            return False
        except Exception:  # noqa: BLE001
            # Cualquier otra cosa --tipicamente NOPERM sobre PING-- si es una
            # respuesta del servidor: hay Redis y ya lo juzgan las cinco
            # comprobaciones, que lo cuentan con su explicacion.
            pass

        return True

    def _check_broker(self):
        """
        Que el Redis valga de broker, que no es lo mismo que valer de cache.

        La ACL de la cache en ``deploy/REDIS.md`` limita las claves a
        ``~gea:*`` y da ``+@read +@write +@keyspace``. Un broker de Celery
        escribe claves con **sus** nombres (``celery``, ``_kombu.binding.*``,
        ``unacked``), usa **pub/sub** para los resultados y **transacciones**
        para no perder mensajes. Nada de eso encaja, y por eso el broker lleva
        usuario propio (paso 9 de ese documento).

        El sintoma de tenerlo mal es de los peores: el Redis responde, la cache
        va, y las tareas desaparecen sin ruido. Por eso se prueba comando a
        comando en vez de dar por hecho que «Redis funciona».
        """
        self._section('2. Redis como broker (no como cache)')

        if not getattr(settings, 'CELERY_BROKER_URL', ''):
            self.stdout.write(
                '   No hay CELERY_BROKER_URL, asi que no hay nada que probar '
                'todavia.'
            )
            self.stdout.write(
                '   El broker NO usa las credenciales de la cache: el usuario '
                '«gea» esta acotado a ~gea:* y responde NOPERM a las cinco '
                'operaciones que hace un broker --PING, encolar, repartir, '
                'pub/sub y transacciones--. Lleva su propio usuario, su propia '
                'contrasena y su propia base de datos.'
            )
            self.stdout.write(
                '   Se monta en cinco minutos siguiendo deploy/REDIS.md '
                '(paso 9) y se declara asi:'
            )
            self.stdout.write(
                '      CELERY_BROKER_URL=rediss://broker:<clave>@'
                'redis.sebasmoralesd.com:6380/1?ssl_cert_reqs=required&'
                'ssl_ca_certs=<ruta de la CA>'
            )
            return False

        try:
            client = self._broker_client()
        except Exception as error:  # noqa: BLE001
            self.stdout.write(self.style.ERROR(
                f'   CELERY_BROKER_URL no se pudo interpretar: '
                f'{type(error).__name__}: {error}'
            ))
            return False

        if not self._broker_answers(client):
            return False

        probe = f'{BROKER_KEY}.probe.{uuid.uuid4().hex[:8]}'

        checks = [
            (
                'PING',
                lambda: client.ping(),
                'Al usuario del broker le falta @connection. Un broker lo usa '
                'para saber si el Redis sigue ahi.',
            ),
            (
                'Claves propias del broker (LPUSH)',
                lambda: client.lpush(probe, b'x'),
                'Al usuario le faltan los patrones de clave que Celery usa de '
                'verdad: ~celery* ~_kombu* ~unacked*.',
            ),
            (
                'Cola de mensajes (BRPOP)',
                lambda: client.brpop(probe, timeout=1),
                'Es como se reparte el trabajo entre workers. Sin esto no hay '
                'cola.',
            ),
            (
                'Pub/sub (PUBLISH)',
                lambda: client.publish(f'{probe}.channel', b'x'),
                'Celery lo usa para los resultados y para hablar con los '
                'workers. Hace falta @pubsub y el patron de canales &*.',
            ),
            (
                'Transacciones (MULTI/EXEC)',
                lambda: client.pipeline(transaction=True).llen(
                    probe).execute(),
                'Es lo que evita perder un mensaje a medio repartir. Hace '
                'falta @transaction.',
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

        isolated = self._check_broker_isolation(client)

        if allowed < len(checks):
            self.stdout.write(self.style.WARNING(
                f'   {allowed} de {len(checks)}. Al usuario del broker le '
                'falta algo. La linea que lo abre entera esta en '
                'deploy/REDIS.md, paso 9.'
            ))
            return False

        if not isolated:
            # Que funcione no basta: un broker que ademas puede leer y borrar
            # las claves de la cache convierte cualquier fuga de su clave en
            # borrar los contadores de intentos.
            return False

        self.stdout.write(self.style.SUCCESS(
            '   El Redis sirve de broker, y el broker no alcanza la cache.'
        ))

        return True

    def _check_broker_isolation(self, client):
        """
        Que el broker **no** alcance las claves de la cache.

        Esta se cuenta al reves que las otras: aqui lo bueno es que responda
        NOPERM. Y no sobra, porque es un error que ya se cometio: la primera
        version del documento daba `~*` al broker y daba por hecho que ponerlo
        en otra base de datos lo separaba de la cache. **Las ACL de Redis no se
        acotan por base de datos**, asi que ese usuario, conectado a la base 0,
        leia y borraba las claves `gea:*` sin problema -- entre ellas los
        contadores de intentos de acceso.

        Quien aisla es el patron de claves. La base aparte sigue siendo buena
        idea por orden, pero no es el control.
        """
        prefix = getattr(settings, 'REDIS_KEY_PREFIX', None) or 'gea'
        target = f'{prefix}:worker-probe-isolation'

        try:
            client.get(target)
        except Exception:  # noqa: BLE001
            self.stdout.write(self.style.SUCCESS(
                f'   Leer las claves de la cache ({target}): DENEGADO, que es '
                'lo correcto.'
            ))
            return True

        self.stdout.write(self.style.ERROR(
            f'   Leer las claves de la cache ({target}): PERMITIDO. El usuario '
            'del broker llega a las claves de la cache.'
        ))
        self.stdout.write(
            '      Probablemente lleve ~* en vez de los tres patrones de '
            'Celery. Ponerlo en otra base de datos NO lo arregla: las ACL de '
            'Redis no se acotan por base. Con ~* , una fuga de la clave del '
            'broker borra los contadores de intentos de acceso.'
        )

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

    def _requested_minutes(self, options) -> int:
        """La duracion pedida, acotada a algo que tenga sentido medir."""
        minutes = options.get('minutes') or PROBE_MAX_MINUTES

        return max(PROBE_MIN_MINUTES, min(PROBE_LIMIT_MINUTES, minutes))

    def _spawn_probe(self, minutes: int):
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

        # La duracion va en el nombre: al leer el rastro mas tarde hay que
        # saber cuanto se esperaba, y puede no ser la de por defecto.
        beats = directory / f'{timezone.now():%Y%m%d-%H%M%S}-{minutes}m.beats'

        script = (
            'import time,sys\n'
            'path=sys.argv[1]\n'
            f'for i in range({int(minutes * 60 / PROBE_BEAT_SECONDS)}):\n'
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
            f'   Lanzado. Late cada {PROBE_BEAT_SECONDS}s durante '
            f'{self._say_duration(minutes)}.'
        ))
        self.stdout.write(f'   Deja su rastro en {beats.name}')
        self.stdout.write('')
        self.stdout.write(
            f'   Vuelve dentro de {self._say_duration(minutes)} y ejecuta el '
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
                '   Todavia no se ha lanzado ninguno. Lanza uno con --spawn '
                f'y vuelve dentro de {self._say_duration(PROBE_MAX_MINUTES)}: '
                'es la comprobacion que decide.'
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
        expected = self._expected_minutes(trace)
        alive = since < 2

        self.stdout.write(
            f'   {len(beats)} latidos en {trace.name}: '
            + (
                f'lleva {self._say_duration(lived)} vivo de '
                f'{self._say_duration(expected)} previstos.'
                if alive else
                f'vivio {self._say_duration(lived)} de '
                f'{self._say_duration(expected)} previstos.'
            )
        )

        if alive:
            remaining = max(0, expected - lived)

            self.stdout.write(self.style.SUCCESS(
                '   Sigue vivo ahora mismo, que ya es buena senal.'
            ))
            self.stdout.write(
                f'   Vuelve dentro de {self._say_duration(remaining)}, cuando '
                'la prueba haya terminado. NO la relances: lanzar otra '
                'empezaria a contar de cero y perderia lo andado.'
            )
            return RUNNING

        if lived >= expected - 1:
            self.stdout.write(self.style.SUCCESS(
                f'   Aguanto la prueba entera ({self._say_duration(expected)}). '
                'Este servidor deja vivir a un proceso desprendido.'
            ))
            self._suggest_longer(expected)
            return True

        if lived >= PROBE_GOOD_MINUTES:
            self.stdout.write(self.style.WARNING(
                f'   Duro {self._say_duration(lived)} y lo mataron antes de '
                'acabar. Un worker aqui se moriria solo cada tanto, en '
                'silencio, y con el las tareas que tuviera a medias.'
            ))
            return False

        self.stdout.write(self.style.ERROR(
            f'   Solo duro {self._say_duration(lived)}. Este hosting no deja '
            'procesos en segundo plano: un worker aqui no se sostiene.'
        ))

        return False

    def _suggest_longer(self, expected: float):
        """
        Lo que falta por saber, con el comando para averiguarlo.

        Media hora descarta el hosting que mata todo enseguida, que es lo mas
        comun, pero no dice nada de si un worker aguanta una semana. Antes
        este aviso pedia dejarlo corriendo un dia sin ofrecer manera de
        hacerlo: la duracion estaba fija en el codigo.
        """
        if expected >= PROBE_LONG_MINUTES:
            self.stdout.write(
                '   Y aguanto una prueba larga, que es lo mas que se puede '
                'saber sin ponerlo en produccion.'
            )
            return

        self.stdout.write(
            f'   Ojo: {self._say_duration(expected)} no son semanas. Lo que '
            'esto descarta es el hosting que mata todo enseguida, que es lo '
            'mas comun, no el que mata un proceso de vez en cuando.'
        )
        self.stdout.write(
            '   Para saber eso, una prueba larga y volver mañana:'
        )
        self.stdout.write(
            f'      manage.py check_workers --spawn --minutes {PROBE_LONG_MINUTES}'
        )

    def _say_duration(self, minutes: float) -> str:
        """Minutos, horas o dias, lo que se lea mejor."""
        if minutes < 90:
            return f'{minutes:.0f} minutos'

        hours = minutes / 60

        if hours < 48:
            return f'{hours:.0f} horas'

        return f'{hours / 24:.0f} dias'

    def _expected_minutes(self, trace) -> int:
        """
        Cuanto se pidio que durase, leido del nombre del rastro.

        Los rastros anteriores a la opcion --minutes no lo llevan, y para esos
        vale el valor por defecto, que es lo que se uso al lanzarlos.
        """
        parts = trace.stem.rsplit('-', 1)

        if len(parts) == 2 and parts[1].endswith('m') and parts[1][:-1].isdigit():
            return int(parts[1][:-1])

        return PROBE_MAX_MINUTES

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
                    'Mientras tanto hay algo que si se puede ir haciendo: '
                    'darle al broker su usuario y su base de datos, sin tocar '
                    'la cache (deploy/REDIS.md, paso 9).'
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
                'El servidor sostiene un proceso, y eso era lo que no se '
                'sabia. Falta el broker.'
            ))
            self.stdout.write(
                'Se abre sin tocar la cache: un usuario propio en redis.conf, '
                'su propia contrasena y la base 1. Esta escrito paso a paso en '
                'deploy/REDIS.md (paso 9), y se declara en el .env con '
                'CELERY_BROKER_URL. Vuelve a ejecutar esto despues.'
            )
            return

        self.stdout.write(self.style.SUCCESS(
            'Este servidor puede sostener un worker.'
        ))
        self.stdout.write(
            'Con una advertencia: media hora de prueba no son semanas de '
            'produccion. Dejalo corriendo un dia antes de fiarle trabajo que '
            'importe.'
        )
