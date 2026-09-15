# apps/common/utils/management/commands/check_realtime.py
"""
Si este montaje aguanta notificaciones en tiempo real, medido y no supuesto.

La plataforma vive en cPanel y el Redis vive en un VPS. Eso permite una cosa
que de otro modo obligaria a mudar la aplicacion entera: **el que publica no
necesita ser un proceso persistente**. Django, dentro de la peticion, escribe
la notificacion en MySQL y hace un ``PUBLISH``; quien tiene que estar vivo todo
el rato es el que retransmite, y ese vive en el VPS. Si eso se sostiene, la
aplicacion se queda donde esta.

Si no se sostiene, la salida es mudar la aplicacion al VPS -- base de datos,
media, estaticos, cron, TLS y una ventana de corte. Es un proyecto en si, y por
eso esta comprobacion va **antes** de escribir una linea del producto: lo que
decide no es el diseno de las notificaciones sino donde puede correr la
aplicacion.

Cinco preguntas, y no todas se contestan igual:

1. **¿Llega cPanel al Redis del VPS para pub/sub?**  Se mide aqui, de punta a
   punta.
2. **¿Cuanto tarda?**  Se mide aqui. Importa mas de lo que parece: con
   ``ATOMIC_REQUESTS`` cada milisegundo de red es tiempo con una transaccion
   abierta.
3. **¿Aguanta este hosting varias conexiones salientes a la vez?**  Se mide
   aqui.
4. **¿Hay un subdominio de tiempo real publicado con TLS?**  Se mide aqui, pero
   solo si se dice cual: no se adivina un nombre de host.
5. **¿Alcanza el VPS a la base de datos de cPanel?**  **No se mide aqui**, y
   decir lo contrario seria mentir: esa conexion sale del VPS, no de esta
   maquina. Lo que hace esta seccion es preparar la comprobacion -- mirar lo
   que si se ve desde aqui y escribir el comando exacto que hay que ejecutar
   alla.

Lo que no se puede medir se dice que no se puede medir. Un comando de
verificacion que da verde a lo que no ha probado es peor que no tenerlo: lleva
a comprometerse con una arquitectura sobre una comprobacion que nunca ocurrio.

    manage.py check_realtime
    manage.py check_realtime --realtime-host rt.propensionesabogados.com

Hermano de ``check_workers``, que contesta la otra mitad --si este servidor
sostiene un proceso en segundo plano y si el Redis vale de broker-- y no se
repite aqui.
"""

import socket
import ssl
import statistics
import time
import uuid
from datetime import datetime, timezone as dt_timezone
from urllib.parse import urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand

# Cuantos PING se mandan para medir la latencia. Uno no mide nada --el primero
# paga el establecimiento de la conexion y el saludo TLS-- y cien tampoco
# aportan: lo que se busca es el orden de magnitud y si hay picos.
LATENCY_SAMPLES = 20

# Conexiones salientes simultaneas que se intentan abrir. Diez no es el numero
# de produccion: es suficiente para ver si el hosting corta a la segunda, que
# es el fallo que se busca.
OUTBOUND_CONNECTIONS = 10

# Cuanto se espera a que el mensaje publicado vuelva por la suscripcion. Si no
# llega en dos segundos por una red que responde en milisegundos, no llega.
PUBSUB_WAIT_SECONDS = 2.0

# Los tramos de latencia. No son gustos: por debajo de 25 ms publicar dentro de
# la peticion no se nota; hasta 100 ms se nota y se aguanta; por encima, cada
# notificacion alarga una transaccion abierta lo que tarda una consulta entera.
LATENCY_GOOD_MS = 25.0
LATENCY_USABLE_MS = 100.0

# Cuando un certificado esta demasiado cerca de caducar como para montar nada
# encima sin renovarlo antes.
CERT_WARN_DAYS = 21

# Hosts que significan «esta misma maquina». Un DB_HOST asi es correcto para
# cPanel y a la vez la respuesta a que el VPS no puede usar ese valor.
LOOPBACK = {'', 'localhost', '127.0.0.1', '::1'}

NOT_ASKED = 'not_asked'

# El subdominio existe y sirve TLS, pero no esta en la maquina que deberia.
WRONG_MACHINE = 'wrong_machine'


class Command(BaseCommand):
    help = (
        'Comprueba si cPanel puede sostener notificaciones en tiempo real '
        'contra el Redis del VPS.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--realtime-host',
            default='',
            help=(
                'El subdominio que retransmitiria los eventos, por ejemplo '
                'rt.propensionesabogados.com. Sin el, esa comprobacion se '
                'salta: no se inventa un nombre de host.'
            ),
        )
        parser.add_argument(
            '--samples',
            type=int,
            default=LATENCY_SAMPLES,
            help=f'Cuantos PING se miden. Por defecto {LATENCY_SAMPLES}.',
        )
        parser.add_argument(
            '--connections',
            type=int,
            default=OUTBOUND_CONNECTIONS,
            help=(
                'Conexiones salientes simultaneas que se intentan abrir. Por '
                f'defecto {OUTBOUND_CONNECTIONS}.'
            ),
        )

    def handle(self, *args, **options):
        verdict = {}

        self._said_no_redis = False

        verdict['pubsub'] = self._check_pubsub()
        verdict['latency'] = self._check_latency(max(2, options['samples']))
        verdict['outbound'] = self._check_outbound(
            max(2, options['connections'])
        )
        verdict['host'] = self._check_realtime_host(
            options['realtime_host'].strip()
        )

        self._report_database()

        self._conclude(verdict)

        return None

    # ------------------------------------------------------------------
    def _section(self, title):
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING(title))

    def _client(self):
        """
        Un cliente **crudo**, no ``django.core.cache``, y no es un detalle.

        La cache de este proyecto lleva ``IGNORE_EXCEPTIONS``, y eso en
        ``django-redis`` no significa que la excepcion se propague envuelta:
        significa que **devuelve ``None`` en vez de lanzar**. Medir el pub/sub
        a traves de la cache daria «no hubo error» con el Redis apagado, que es
        exactamente la clase de verde falso que este comando existe para no
        dar.
        """
        import redis

        return redis.Redis.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=5,
            socket_timeout=5,
        )

    def _diagnose(self, error) -> str:
        """
        Si el servidor contesto que no, o si no hay servidor.

        Es la misma distincion que hace ``check_workers`` con el broker, y por
        el mismo motivo: son dos averias que no se parecen en nada y se
        arreglan en sitios distintos --una linea de ACL, o el cortafuegos-- y
        sin separarlas el comando manda a mirar donde no es. La da el tipo de
        error: un NOPERM llega como ``ResponseError``, o sea que **hubo
        respuesta**, mientras que un servidor inalcanzable llega como
        ``ConnectionError`` o ``TimeoutError``, que no son respuestas suyas.
        """
        import redis

        if isinstance(error, redis.exceptions.AuthenticationError):
            return 'auth'

        if isinstance(error, (redis.exceptions.ConnectionError,
                              redis.exceptions.TimeoutError)):
            return 'unreachable'

        if isinstance(error, redis.exceptions.ResponseError):
            return 'refused'

        return 'unknown'

    def _explain(self, error):
        """Escribir la explicacion que le toca a esa averia, y solo esa."""
        clase = self._diagnose(error)

        if clase == 'auth':
            self.stdout.write(
                '      El usuario o la contrasena de REDIS_URL no son los del '
                'Redis. Esto es anterior a cualquier ACL.'
            )
        elif clase == 'unreachable':
            self.stdout.write(
                '      No se llega al servidor, asi que esto no dice nada de '
                'la ACL: puede estar perfecta. Mira el host y el puerto de '
                'REDIS_URL, la ruta de la CA y el cortafuegos '
                '(deploy/REDIS.md, paso 5). Y si no se llega, la cache '
                'tampoco esta funcionando.'
            )
        elif clase == 'refused':
            self.stdout.write(
                '      El servidor contesto, y contesto que no: es la ACL, no '
                'la red. Se arregla en una linea de redis.conf.'
            )

        return clase

    def _prefix(self) -> str:
        return getattr(settings, 'REDIS_KEY_PREFIX', None) or 'gea'

    def _round_trip(self, client):
        """
        Una ida y vuelta con **lo que la aplicacion hace de verdad**.

        Aqui habia un ``PING``, y era la eleccion equivocada por un motivo que
        solo se ve ejecutandolo contra el Redis de produccion: al usuario de la
        cache **no se le concede `@connection`**, a proposito, porque la cache
        no necesita hacer ping. Asi que las dos secciones que median con PING
        contestaban «no se pudo medir» en un Redis que funciona perfectamente,
        y la salida invitaba a abrir un permiso para poder diagnosticar.

        Un diagnostico que pide ensanchar la ACL para poder ejecutarse esta
        midiendo otra cosa. Una lectura de una clave `gea:` es justo lo que
        hace la aplicacion en cada comprobacion de limite, entra en `~gea:*`
        con la ACL que ya hay, y como la clave no existe el servidor contesta
        nil: el coste es el viaje, que es lo que se queria medir.
        """
        return client.get(f'{self._prefix()}:rt.round-trip-probe')

    def _no_redis(self) -> bool:
        """
        Si no hay a donde conectarse. Se explica una vez, no tres.

        Las tres primeras secciones miden contra el mismo Redis, asi que sin
        ``REDIS_URL`` las tres se quedan sin nada que medir. Repetir el parrafo
        entero tres veces hace que se lea cero: lo que queda en pantalla
        parecen tres averias distintas.
        """
        if getattr(settings, 'REDIS_URL', ''):
            return False

        if self._said_no_redis:
            self.stdout.write('   Sin REDIS_URL (ver la seccion 1).')
            return True

        self._said_no_redis = True

        self.stdout.write(self.style.ERROR(
            '   No hay REDIS_URL, asi que no hay nada que medir.'
        ))
        self.stdout.write(
            '      Sin ella Django ni siquiera usa Redis: cae en LocMemCache, '
            'que es por proceso -- y entonces el tiempo real no es lo primero '
            'que falta, porque los contadores de intentos ya van por worker. '
            'Montaje en deploy/REDIS.md.'
        )

        return True

    # ------------------------------------------------------------------
    def _check_pubsub(self):
        """
        Que un mensaje publicado desde cPanel salga por una suscripcion.

        Se prueba entero --suscribir, publicar, recibir-- y no solo publicando,
        porque ``PUBLISH`` **no falla cuando no hay nadie escuchando**:
        devuelve 0 receptores y eso es una respuesta valida. Comprobarlo solo
        con el numero de retorno daria por bueno un canal que nadie puede oir.

        Y se prueba con las credenciales de la **cache**, no con las del
        broker, porque el canal de notificaciones es el de Django: si hiciera
        falta un tercer usuario de Redis para esto, eso tambien es un hallazgo.

        La trampa concreta de aqui: **los patrones de clave de una ACL no
        gobiernan los canales**. Un usuario con ``~gea:*`` puede escribir las
        claves de la cache y responder NOPERM a un PUBLISH, porque los canales
        se conceden aparte, con patrones ``&``. Es la misma sorpresa que se
        llevo el broker con ``~celery*``, en otro sitio.
        """
        self._section('1. Pub/sub de cPanel al Redis del VPS')

        if self._no_redis():
            return False

        channel = f'{self._prefix()}:rt.probe.{uuid.uuid4().hex[:8]}'
        payload = uuid.uuid4().hex.encode()

        try:
            listener = self._client()
            publisher = self._client()
        except Exception as error:  # noqa: BLE001
            self.stdout.write(self.style.ERROR(
                f'   REDIS_URL no se pudo interpretar: '
                f'{type(error).__name__}: {error}'
            ))
            return False

        # `ignore_subscribe_messages` queda en False **a proposito**: la
        # confirmacion del SUBSCRIBE es justo lo que hay que leer, y con eso
        # puesto se descarta sin mirarla.
        subscription = listener.pubsub()

        if not self._subscribed(subscription, channel):
            self._close(subscription, listener, publisher)
            return False

        try:
            receptores = publisher.publish(channel, payload)
        except Exception as error:  # noqa: BLE001
            self.stdout.write(self.style.ERROR(
                f'   PUBLISH: {type(error).__name__}: {error}'
            ))
            self._explain(error)
            self.stdout.write(
                '      Suscribirse y publicar son permisos distintos: se puede '
                'tener uno y no el otro.'
            )
            self._close(subscription, listener, publisher)
            return False

        self.stdout.write(self.style.SUCCESS(
            f'   PUBLISH: permitido ({receptores} receptor/es)'
        ))

        llego = self._wait_for(subscription, payload)

        self._close(subscription, listener, publisher)

        if not llego:
            self.stdout.write(self.style.ERROR(
                '   El mensaje NO volvio por la suscripcion.'
            ))
            self.stdout.write(
                '      Publicar y suscribirse dieron permiso, asi que no es la '
                'ACL. Lo que queda es que las dos conexiones no esten hablando '
                'con el mismo Redis --un balanceador delante, o un cluster sin '
                'propagacion de pub/sub entre nodos--, que es justo lo que '
                'rompe el tiempo real sin romper la cache.'
            )
            return False

        self.stdout.write(self.style.SUCCESS(
            '   El mensaje volvio: el canal funciona de punta a punta.'
        ))

        return True

    def _subscribed(self, subscription, channel) -> bool:
        """
        Suscribirse **y esperar a que el servidor lo confirme**.

        Las dos mitades hacen falta, y saltarse la segunda rompe esto de dos
        maneras distintas.

        Una: ``subscribe()`` de redis-py escribe el comando y **no lee la
        respuesta** -- la lee el primer ``get_message``. Asi que un NOPERM no
        salta donde uno se suscribe: salta despues, lejos, o no salta. Probado
        contra un Redis real con la ACL de la cache (``resetchannels``), la
        suscripcion se daba por buena y el fallo aparecia tres secciones mas
        abajo disfrazado de otra cosa.

        Y dos: aunque hubiera permiso, publicar antes de que el servidor tenga
        registrada la suscripcion pierde el mensaje. Seria un fallo
        intermitente en la comprobacion, que es la peor clase: el comando
        diria que el canal no funciona en un montaje perfecto, una vez de cada
        tantas.
        """
        try:
            subscription.subscribe(channel)
        except Exception as error:  # noqa: BLE001
            self.stdout.write(self.style.ERROR(
                f'   SUBSCRIBE: {type(error).__name__}: {error}'
            ))
            self._explain(error)
            return False

        limite = time.monotonic() + PUBSUB_WAIT_SECONDS

        while time.monotonic() < limite:
            try:
                message = subscription.get_message(timeout=0.2)
            except Exception as error:  # noqa: BLE001
                self.stdout.write(self.style.ERROR(
                    f'   SUBSCRIBE: {type(error).__name__}: {error}'
                ))

                if self._diagnose(error) == 'refused':
                    self.stdout.write(
                        '      Al usuario le faltan los canales. Los patrones '
                        'de clave NO los conceden: `~gea:*` deja escribir las '
                        'claves de la cache y aun asi responde NOPERM aqui, '
                        'porque los canales van aparte, con `&`. Es la misma '
                        'sorpresa que se llevo el broker con `~celery*`.'
                    )
                else:
                    self._explain(error)

                return False

            if message and message.get('type') == 'subscribe':
                self.stdout.write(self.style.SUCCESS(
                    '   SUBSCRIBE: confirmado por el servidor'
                ))
                return True

        self.stdout.write(self.style.ERROR(
            '   SUBSCRIBE: el servidor no lo confirmo.'
        ))
        self.stdout.write(
            '      Ni permitido ni denegado: no contesto. Con un Redis que '
            'responde al PING, esto apunta a que algo se come el trafico de '
            'pub/sub entre medias.'
        )

        return False

    def _wait_for(self, subscription, payload) -> bool:
        """Esperar el mensaje propio, descartando lo que no lo sea."""
        limite = time.monotonic() + PUBSUB_WAIT_SECONDS

        while time.monotonic() < limite:
            try:
                message = subscription.get_message(timeout=0.2)
            except Exception:  # noqa: BLE001
                return False

            if (message and message.get('type') == 'message'
                    and message.get('data') == payload):
                return True

        return False

    def _close(self, *closeables):
        for item in closeables:
            try:
                item.close()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    def _check_latency(self, samples: int):
        """
        Cuanto tarda un ida y vuelta a ese Redis, que es tiempo de transaccion.

        Con ``ATOMIC_REQUESTS`` toda la vista va dentro de una transaccion, asi
        que publicar dentro de la peticion alarga lo que una transaccion tiene
        abierto. Publicar en ``transaction.on_commit`` --que es lo que hay que
        hacer, y por otra razon: un rollback no puede dejar anunciado algo que
        no paso-- lo saca de la transaccion, pero **no** de la peticion: el
        usuario sigue esperando.

        El primer PING no cuenta: paga el establecimiento de la conexion y el
        saludo TLS, que se hacen una vez y no en cada publicacion.
        """
        self._section('2. Latencia de cPanel al VPS')

        if self._no_redis():
            return None

        try:
            client = self._client()
            self._round_trip(client)
        except Exception as error:  # noqa: BLE001
            # Decia «no se llega al Redis» pasara lo que pasara, y con la ACL
            # de la cache eso era falso: el Redis estaba ahi y contestaba.
            # Mandaba a mirar el cortafuegos por un problema de permisos.
            self.stdout.write(self.style.ERROR(
                f'   No se pudo medir: {type(error).__name__}: {error}'
            ))
            self._explain(error)
            return None

        medidas = []

        for _ in range(samples):
            arranque = time.perf_counter()

            try:
                self._round_trip(client)
            except Exception as error:  # noqa: BLE001
                self.stdout.write(self.style.ERROR(
                    f'   La conexion se corto a mitad de la medicion: '
                    f'{type(error).__name__}: {error}'
                ))
                self._close(client)
                return None

            medidas.append((time.perf_counter() - arranque) * 1000)

        self._close(client)

        mediana = statistics.median(medidas)
        peor = max(medidas)

        self.stdout.write(
            f'   {len(medidas)} idas y vueltas: mediana {mediana:.1f} ms, '
            f'la peor {peor:.1f} ms.'
        )
        self.stdout.write(
            '   (La primera no cuenta: paga la conexion y el saludo TLS, que '
            'se hacen una vez. Se mide leyendo una clave, que es lo que hace '
            'la aplicacion, y no con PING, que el usuario de la cache no '
            'necesita ni tiene.)'
        )

        if mediana <= LATENCY_GOOD_MS:
            self.stdout.write(self.style.SUCCESS(
                '   Publicar dentro de la peticion no se va a notar.'
            ))
        elif mediana <= LATENCY_USABLE_MS:
            self.stdout.write(self.style.WARNING(
                '   Se nota pero se aguanta. Publica en transaction.on_commit '
                'para no pagarlo con la transaccion abierta.'
            ))
        else:
            self.stdout.write(self.style.ERROR(
                f'   Mas de {LATENCY_USABLE_MS:.0f} ms de mediana: cada '
                'notificacion alarga la peticion lo que una consulta entera.'
            ))
            self.stdout.write(
                '      Con esto, publicar sincronicamente deja de ser buena '
                'idea aunque funcione: o se encola, o la aplicacion se mueve '
                'al lado del Redis.'
            )

        if peor > LATENCY_USABLE_MS and mediana <= LATENCY_USABLE_MS:
            self.stdout.write(self.style.WARNING(
                f'   Ojo al pico de {peor:.1f} ms: la mediana esta bien pero '
                'hay idas y vueltas que se van. Una mediana buena con picos '
                'malos se ve en produccion como peticiones que a veces tardan '
                'sin motivo aparente.'
            ))

        return {'median_ms': mediana, 'worst_ms': peor}

    # ------------------------------------------------------------------
    def _check_outbound(self, connections: int):
        """
        Si el hosting deja abrir varias conexiones salientes a la vez.

        ``check_workers`` cuenta **procesos**; esto cuenta **sockets**, que es
        otro limite y en hosting compartido tambien lo hay. Importa porque el
        montaje propuesto suma conexiones salientes a las que ya hay: la cache,
        el broker y el pub/sub, multiplicado por cada worker de Apache.

        Se abren de verdad y a la vez --no una detras de otra-- porque el
        limite es de simultaneidad: abrir y cerrar mil, de una en una, no lo
        toca.
        """
        self._section('3. Conexiones salientes simultaneas')

        if self._no_redis():
            return False

        abiertas = []
        fallo = None

        for _ in range(connections):
            try:
                client = self._client()
                self._round_trip(client)
            except Exception as error:  # noqa: BLE001
                fallo = error
                break

            abiertas.append(client)

        logradas = len(abiertas)

        self._close(*abiertas)

        if fallo is not None:
            # Un NOPERM aqui no es un tope de conexiones: la conexion se abrio
            # perfectamente y lo que fallo fue la lectura. Contarlo como «se
            # abrieron 0 de 10» era acusar al hosting de algo que hacia la ACL.
            if self._diagnose(fallo) in ('refused', 'auth'):
                self.stdout.write(self.style.WARNING(
                    f'   No se puede medir con este usuario: '
                    f'{type(fallo).__name__}: {fallo}'
                ))
                self.stdout.write(
                    '      La conexion se abrio; lo que no le dejan es leer. '
                    'Eso es la ACL y no un tope de conexiones. Arregla la '
                    'seccion 1 y vuelve.'
                )
                return None

            self.stdout.write(self.style.ERROR(
                f'   Se abrieron {logradas} de {connections}. La siguiente '
                f'fallo: {type(fallo).__name__}: {fallo}'
            ))
            self.stdout.write(
                '      Si el corte llega siempre en el mismo numero, es un '
                'tope del proveedor y no una averia. Con el tiempo real '
                'encima, ese tope se reparte entre todos los procesos que '
                'atienden la web.'
            )
            return False

        self.stdout.write(self.style.SUCCESS(
            f'   {logradas} conexiones simultaneas, todas vivas a la vez.'
        ))
        self.stdout.write(
            '   No es el numero de produccion: es suficiente para descartar un '
            'hosting que corta a la segunda.'
        )

        return True

    # ------------------------------------------------------------------
    def _check_realtime_host(self, host: str):
        """
        Que el subdominio de tiempo real exista y sirva TLS.

        Sin ``--realtime-host`` no se comprueba nada, y eso **no cuenta como
        fallo**: es una pregunta que no se ha hecho. Adivinar el nombre --
        probar `rt.` del dominio de produccion y darlo por bueno o por malo--
        contestaria sobre un host que nadie dijo que fuera el.

        Se mira lo que decide: que el nombre resuelva, que acepte conexion, que
        el saludo TLS lo haga un certificado valido para **ese** nombre, y
        cuanto le queda. El navegador va a abrir un socket contra ese host
        desde una pagina servida en https: un certificado que no valga ahi no
        da un aviso que se pueda saltar, corta la conexion y ya esta.
        """
        self._section('4. Subdominio de tiempo real')

        if not host:
            self.stdout.write(
                '   No se ha dicho cual es, asi que no se comprueba. Cuando lo '
                'haya:'
            )
            self.stdout.write(
                '      manage.py check_realtime --realtime-host '
                'rt.propensionesabogados.com'
            )
            return NOT_ASKED

        host = self._bare_host(host)

        try:
            direcciones = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        except OSError as error:
            self.stdout.write(self.style.ERROR(
                f'   {host} no resuelve: {error}'
            ))
            self.stdout.write(
                '      Falta el registro DNS apuntando al VPS. Es el primer '
                'paso y el unico que no depende de nada mas.'
            )
            return False

        ip = direcciones[0][4][0]

        self.stdout.write(f'   {host} resuelve a {ip}.')

        contexto = ssl.create_default_context()

        try:
            with socket.create_connection((host, 443), timeout=10) as crudo:
                with contexto.wrap_socket(crudo, server_hostname=host) as tls:
                    certificado = tls.getpeercert()
                    version = tls.version()
        except ssl.SSLCertVerificationError as error:
            self.stdout.write(self.style.ERROR(
                f'   El certificado de {host} no vale: {error}'
            ))
            self.stdout.write(
                '      Desde una pagina en https esto no es un aviso que el '
                'usuario pueda aceptar: el navegador corta el socket sin '
                'preguntar, y el tiempo real no llega a abrirse.'
            )
            return False
        except OSError as error:
            self.stdout.write(self.style.ERROR(
                f'   No se pudo conectar a {host}:443: '
                f'{type(error).__name__}: {error}'
            ))
            self.stdout.write(
                '      El nombre resuelve, asi que el DNS esta. Lo que falta '
                'es que algo escuche en el 443 del VPS, o que el cortafuegos '
                'lo deje pasar.'
            )
            return False

        self.stdout.write(self.style.SUCCESS(
            f'   Saludo TLS correcto ({version}).'
        ))

        self._say_expiry(certificado)

        return self._say_which_machine(host, {d[4][0] for d in direcciones})

    def _say_which_machine(self, host, direcciones):
        """
        En que maquina esta ese subdominio, que es la pregunta de verdad.

        Que resuelva y sirva TLS no dice nada de **donde** esta, y el relay
        tiene que vivir donde vive el Redis. Comprobado en produccion:
        `rt.propensionesabogados.com` existe, tiene certificado valido y
        contesta -- y apunta a la misma direccion que la propia aplicacion, o
        sea al cPanel. El registro esta creado; lo que no esta es apuntando al
        VPS.

        Un «saludo TLS correcto» a secas ahi es media verdad, de las que
        cuestan una tarde: se da la seccion por buena, se monta el relay en el
        VPS y el navegador sigue abriendo el socket contra cPanel, donde no hay
        nada escuchando.

        Asi que se compara contra las dos maquinas que ya se conocen --la del
        Redis (`REDIS_URL`) y la de la aplicacion (`PUBLIC_BASE_URL`)-- y se
        dice cual de las dos es. Ninguna de las dos resuelve por su cuenta a
        una tercera cosa, asi que cuando no coincide con ninguna no se
        adivina: se dice lo que se ve.
        """
        del_redis = self._addresses(self._host_of(
            getattr(settings, 'REDIS_URL', '')))
        del_sitio = self._addresses(self._host_of(
            getattr(settings, 'PUBLIC_BASE_URL', '')))

        if del_redis and direcciones & del_redis:
            self.stdout.write(self.style.SUCCESS(
                '   Y esta en la misma maquina que el Redis, que es donde '
                'tiene que estar el relay.'
            ))
            return True

        if del_sitio and direcciones & del_sitio:
            self.stdout.write(self.style.WARNING(
                f'   Pero {host} apunta a la MISMA maquina que sirve la '
                'aplicacion, no al VPS.'
            ))
            self.stdout.write(
                '      El registro existe y el certificado vale, asi que esta '
                'seccion parecia resuelta. No lo esta: el relay vive donde '
                'vive el Redis, y el navegador abriria el socket contra '
                'cPanel, donde no hay nada escuchando. Lo que falta es '
                'apuntar el registro al VPS (o, si se prefiere dejarlo aqui, '
                'un proxy de WebSocket en Apache, que es otra arquitectura y '
                'hay que decidirla a proposito).'
            )
            return WRONG_MACHINE

        self.stdout.write(
            '   No es ni la maquina del Redis ni la de la aplicacion. '
            'Comprueba que sea el VPS.'
        )

        return True

    def _host_of(self, url: str) -> str:
        """El nombre de host de una URL, o vacio si no lo tiene."""
        if not url:
            return ''

        try:
            return urlsplit(url).hostname or ''
        except ValueError:
            return ''

    def _addresses(self, host: str):
        """Las direcciones de un host, o None si no se pudo resolver."""
        if not host:
            return None

        try:
            return {d[4][0] for d in socket.getaddrinfo(
                host, None, proto=socket.IPPROTO_TCP)}
        except OSError:
            return None

    def _bare_host(self, host: str) -> str:
        """Quedarse con el nombre, venga como venga escrito."""
        if '//' in host:
            host = urlsplit(host).netloc or host

        host = host.split('/')[0].strip()

        # Un puerto detras del nombre; el `:` de una IPv6 entre corchetes no.
        if host.count(':') == 1 and not host.startswith('['):
            host = host.split(':')[0]

        return host

    def _say_expiry(self, certificado):
        """Cuanto le queda al certificado, si se puede leer."""
        vence = (certificado or {}).get('notAfter')

        if not vence:
            return

        try:
            fecha = datetime.strptime(
                vence, '%b %d %H:%M:%S %Y %Z'
            ).replace(tzinfo=dt_timezone.utc)
        except ValueError:
            self.stdout.write(f'   Caduca: {vence}')
            return

        quedan = (fecha - datetime.now(dt_timezone.utc)).days

        if quedan <= CERT_WARN_DAYS:
            self.stdout.write(self.style.WARNING(
                f'   Caduca en {quedan} dias ({vence}). Renuevalo antes de '
                'montar nada encima.'
            ))
        else:
            self.stdout.write(f'   Caduca en {quedan} dias ({vence}).')

    # ------------------------------------------------------------------
    def _report_database(self):
        """
        Lo que hace falta para que el worker del VPS alcance esta base de datos.

        **Esta seccion no comprueba nada**, y es a proposito. La conexion que
        importa sale del VPS y llega a cPanel; desde cPanel lo unico que se
        puede medir es cPanel llegando a su propia base de datos, que ya se
        sabe que funciona y no contesta la pregunta. Dar verde aqui seria dar
        verde a una comprobacion que no ha ocurrido.

        Lo que si se puede hacer desde aqui es mirar la configuracion y
        escribir el comando exacto para el otro lado. La contrasena no se
        imprime: la salida de un comando de la consola de operaciones acaba
        escrita en ``CommandRunModel``.
        """
        self._section('5. La base de datos, desde el VPS (no se mide aqui)')

        datos = settings.DATABASES['default']
        motor = datos.get('ENGINE', '')
        anfitrion = (datos.get('HOST') or '').strip()
        puerto = datos.get('PORT')
        usuario = datos.get('USER') or ''
        nombre = datos.get('NAME') or ''

        self.stdout.write(
            '   Configurado: {}{}, base {}, usuario {}.'.format(
                anfitrion or '(sin host)',
                f':{puerto}' if puerto else '',
                nombre or '(sin nombre)',
                usuario or '(sin usuario)',
            )
        )

        if anfitrion.lower() in LOOPBACK:
            self.stdout.write(self.style.WARNING(
                '   DB_HOST apunta a esta misma maquina. Para cPanel es lo '
                'correcto, y a la vez es la respuesta: el VPS no puede usar '
                'ese valor.'
            ))
            self.stdout.write(
                '      Hace falta el nombre publico del servidor de cPanel, '
                'la IP del VPS dada de alta en Remote MySQL, y el usuario '
                'concedido desde esa IP -- un GRANT a \'usuario\'@\'localhost\' '
                'no sirve para una conexion que llega de fuera.'
            )

        if 'mysql' in motor:
            self.stdout.write('   Desde el VPS, ejecuta:')
            self.stdout.write(
                f'      mysql -h <host publico de cPanel> -P {puerto} '
                f'-u {usuario} -p --ssl-mode=REQUIRED {nombre} '
                '-e "SELECT 1"'
            )
            self.stdout.write(
                '   Sin --ssl-mode=REQUIRED la contrasena y los datos viajan '
                'por Internet en claro entre las dos maquinas.'
            )
        elif 'postgresql' in motor:
            self.stdout.write('   Desde el VPS, ejecuta:')
            self.stdout.write(
                f'      psql "host=<host publico de cPanel> port={puerto} '
                f'user={usuario} dbname={nombre} sslmode=require" -c "SELECT 1"'
            )
        else:
            self.stdout.write(
                f'   Motor {motor}: comprueba a mano que el VPS llega, con TLS.'
            )

        self.stdout.write(
            '   Si no llega, el worker no puede escribir entregas ni leer '
            'plantillas, y el diseno cambia: el correo tendria que salir desde '
            'cPanel y el VPS quedarse solo con el reparto de eventos.'
        )

    # ------------------------------------------------------------------
    def _conclude(self, verdict):
        """Juntarlo en una respuesta, sin adornarla."""
        self.stdout.write('')

        if not getattr(settings, 'REDIS_URL', ''):
            self.stdout.write(self.style.ERROR(
                'No se ha medido nada: no hay Redis configurado en esta '
                'maquina.'
            ))
            self.stdout.write(
                'Esto no dice que el tiempo real no se sostenga -- dice que la '
                'pregunta no se ha llegado a hacer. Pon REDIS_URL y vuelve.'
            )
            return

        if not verdict.get('pubsub'):
            self.stdout.write(self.style.ERROR(
                'El tiempo real desde cPanel NO se sostiene: el canal no '
                'funciona.'
            ))
            self.stdout.write(
                'Es lo primero que hay que arreglar, porque lo demas se apoya '
                'en ello. Si el motivo es la ACL se abre en minutos '
                '(deploy/REDIS.md); si es que no se llega al servidor, eso ya '
                'afecta tambien a la cache.'
            )
            return

        if verdict.get('outbound') is False:
            self.stdout.write(self.style.WARNING(
                'El canal funciona, pero este hosting corta las conexiones '
                'salientes antes de lo que hace falta.'
            ))
            self.stdout.write(
                'Con eso, anadir pub/sub a lo que ya hay se come plazas que '
                'atienden la web. Merece una consulta al proveedor antes de '
                'comprometerse.'
            )
            return

        host = verdict.get('host')

        if host is False:
            self.stdout.write(self.style.WARNING(
                'El canal funciona desde cPanel. Falta el subdominio que lo '
                'sirve al navegador.'
            ))
            self.stdout.write(
                'Es trabajo de sistemas en el VPS --DNS, un proceso que '
                'escuche y un certificado--, no de la aplicacion.'
            )
            return

        if host == WRONG_MACHINE:
            self.stdout.write(self.style.WARNING(
                'El canal funciona desde cPanel, y el subdominio existe pero '
                'esta en la maquina equivocada.'
            ))
            self.stdout.write(
                'Es lo mas facil de dar por resuelto de todo esto, porque '
                'responde: un registro DNS que hay que apuntar al VPS.'
            )
            return

        if host == NOT_ASKED:
            self.stdout.write(self.style.SUCCESS(
                'La mitad que depende de esta maquina esta: se publica, se '
                'recibe y se llega.'
            ))
            self.stdout.write(
                'Queda el subdominio de tiempo real, que no se ha preguntado. '
                'Vuelve con --realtime-host cuando exista.'
            )
        else:
            self.stdout.write(self.style.SUCCESS(
                'Las cuatro que se miden desde aqui salen bien: la aplicacion '
                'puede quedarse en cPanel.'
            ))

        latencia = verdict.get('latency')

        if latencia and latencia['median_ms'] > LATENCY_USABLE_MS:
            self.stdout.write(self.style.WARNING(
                'Con la latencia medida, publica siempre fuera de la peticion.'
            ))

        self.stdout.write(
            'Falta la quinta, que no se mide aqui: que el VPS alcance esta '
            'base de datos. Ejecuta alla el comando de la seccion 5 antes de '
            'darlo por hecho.'
        )
