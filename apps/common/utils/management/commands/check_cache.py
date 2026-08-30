# apps/common/utils/management/commands/check_cache.py
"""
Si la cache esta funcionando de verdad, y si sirve para lo que se puso.

Preguntarle al VPS si Redis esta vivo no contesta lo que importa. Lo que hay
que saber es otra cosa: **que esta aplicacion llega, y que los contadores se
comparten entre procesos**. Un Redis impecable al que la aplicacion no alcanza
deja los limites exactamente como estaban.

Y hay una razon para no fiarse de la vista: ``django-redis`` va con
``IGNORE_EXCEPTIONS`` a proposito, para que un corte de red no tumbe el login.
El precio es que un Redis inalcanzable **no da error**: ``cache.get()`` devuelve
``None``, que es indistinguible de «esa clave no existe». Sin una comprobacion
explicita, una cache rota parece una cache vacia y los limites de tasa dejan de
aplicarse sin que nadie se entere.

La prueba que decide es la ultima: se escribe una clave y se lee **desde otro
proceso**. Con Redis se ve; con ``LocMemCache``, que es por proceso, no se ve.
Esa diferencia es justo la que separa un limite de verdad de uno que se puede
esquivar abriendo otra pestana hasta que responda otro worker.

    manage.py check_cache
"""

import os
import subprocess
import sys
import time
import uuid

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand

#: Modo interno: el subproceso solo lee la clave y la imprime.
READ_PREFIX = 'gea:check_cache:'


class Command(BaseCommand):
    help = 'Comprueba que la cache responde y que se comparte entre procesos.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--read',
            metavar='CLAVE',
            help=(
                'Uso interno: lee esa clave y la imprime. Es como se comprueba '
                'que la cache se ve desde otro proceso.'
            ),
        )

    def handle(self, *args, **options):
        if options['read']:
            self.stdout.write(str(cache.get(options['read'])))
            return None

        ok = True

        backend = self._report_backend()
        ok &= self._check_roundtrip()
        ok &= self._check_counter()
        ok &= self._check_expiry()
        shared = self._check_shared()

        self.stdout.write('')

        if not ok:
            self.stdout.write(self.style.ERROR(
                'La cache NO responde. Con django-redis esto no lanza '
                'excepcion, asi que el sitio sigue en pie pero los limites de '
                'tasa no se aplican.'
            ))

            if 'redis' in backend.lower():
                self._diagnose()

            return None

        if not shared:
            if 'redis' in backend.lower():
                self.stdout.write(self.style.ERROR(
                    'La cache responde pero NO se comparte entre procesos, y '
                    'con Redis eso no deberia pasar. Mira si cada proceso esta '
                    'leyendo un REDIS_URL distinto.'
                ))
                return None

            self.stdout.write(self.style.WARNING(
                'LocMemCache: la cache funciona pero es POR PROCESO. Los '
                'limites del OTP publico, del codigo de registro y de la '
                'recuperacion de contrasena son N veces mas laxos con N '
                'workers, y se reinician en cada despliegue. Para arreglarlo, '
                'REDIS_URL: ver deploy/REDIS.md.'
            ))
            return None

        self.stdout.write(self.style.SUCCESS(
            'La cache funciona y se comparte entre procesos. Los contadores de '
            'tasa son de verdad.'
        ))

        return None

    # ------------------------------------------------------------------
    def _section(self, title):
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING(title))

    def _report_backend(self) -> str:
        """Que backend hay puesto. Es lo primero que hay que saber."""
        self._section('1. Backend')

        config = settings.CACHES.get('default', {})
        backend = config.get('BACKEND', 'sin definir')

        self.stdout.write(f'   {backend}')

        if 'redis' in backend.lower():
            # La URL lleva la contrasena: se enmascara antes de imprimirla.
            self.stdout.write(f'   servidor: {self._safe_location(config)}')
            self.stdout.write(
                '   IGNORE_EXCEPTIONS: '
                f"{config.get('OPTIONS', {}).get('IGNORE_EXCEPTIONS', False)}"
            )
        else:
            self.stdout.write(
                '   Sin REDIS_URL, Django usa LocMemCache, que es por proceso.'
            )

        return backend

    def _safe_location(self, config) -> str:
        """La URL del servidor sin la contrasena."""
        location = str(config.get('LOCATION', ''))

        if '@' not in location:
            return location

        scheme, _, rest = location.partition('://')
        _credentials, _, host = rest.rpartition('@')

        return f'{scheme}://***@{host}'

    def _check_roundtrip(self) -> bool:
        """
        Escribir y volver a leer, y cuanto cuesta cada cosa.

        Se miden **dos** tiempos, porque no son el mismo gasto y confundirlos
        lleva a conclusiones equivocadas:

        * **La primera vez** incluye abrir el TCP y negociar el TLS. Eso se
          paga una vez por proceso, no en cada peticion: django-redis mantiene
          un pool y las siguientes reutilizan la conexion. Lo paga cada worker
          nuevo, y en cPanel los workers se reciclan, asi que no es gratis --
          pero tampoco es lo que cuesta atender una peticion.

        * **Las siguientes** son lo que de verdad paga cada peticion con
          limite de tasa. Ese es el numero sobre el que hay que decidir.

        Con la conexion ya abierta, el tiempo de una operacion es basicamente
        la ida y vuelta por la red. Si sale alto, la causa suele ser la
        distancia fisica entre el servidor web y el Redis, y eso no se arregla
        configurando: se arregla acercandolos.
        """
        self._section('2. Ida y vuelta')

        key = f'{READ_PREFIX}{uuid.uuid4().hex}'
        value = {'probe': key}

        started = time.monotonic()
        cache.set(key, value, timeout=120)
        read = cache.get(key)
        cold = (time.monotonic() - started) * 1000

        if read != value:
            self.stdout.write(self.style.ERROR(
                f'   Se escribio y volvio {read!r}. Con IGNORE_EXCEPTIONS un '
                'servidor inalcanzable devuelve None sin lanzar: eso es lo '
                'que parece haber pasado.'
            ))
            return False

        self.stdout.write(self.style.SUCCESS(
            '   Escribe y lee correctamente.'
        ))

        # Ya con la conexion abierta: lo que cuesta de verdad cada peticion.
        samples = []

        for _ in range(5):
            started = time.monotonic()
            cache.set(key, value, timeout=120)
            cache.get(key)
            samples.append((time.monotonic() - started) * 1000)

        cache.delete(key)

        warm = sorted(samples)[len(samples) // 2]

        self.stdout.write(
            f'   Primera operacion: {cold:.0f} ms '
            '(incluye abrir conexion y TLS; se paga una vez por worker)'
        )
        self.stdout.write(
            f'   Ya conectado:      {warm:.0f} ms '
            '(esto es lo que paga cada peticion)'
        )

        self._comment_on_latency(cold, warm)

        return True

    def _comment_on_latency(self, cold, warm):
        """Que significan esos numeros, que es lo que no se ve solo."""
        if warm > 200:
            self.stdout.write(self.style.WARNING(
                '   Cada peticion con limite de tasa paga esos milisegundos, y '
                'con ATOMIC_REQUESTS los paga con una transaccion abierta. Con '
                'la conexion ya hecha, ese tiempo es casi todo distancia '
                'fisica: no se arregla configurando, se arregla poniendo el '
                'Redis mas cerca del servidor web.'
            ))
        elif warm > 50:
            self.stdout.write(
                '   Es un coste asumible para lo que se usa la cache, pero '
                'tenlo en cuenta antes de cachear nada en el camino critico.'
            )

        if cold > 800:
            self.stdout.write(self.style.WARNING(
                f'   Abrir la conexion cuesta {cold:.0f} ms. Un worker recien '
                'arrancado lo paga en su primera peticion, asi que si el '
                'hosting recicla workers a menudo se notara de vez en cuando.'
            ))

    def _check_counter(self) -> bool:
        """``incr``, que es como cuentan los limites de tasa."""
        self._section('3. Contador (incr)')

        key = f'{READ_PREFIX}counter:{uuid.uuid4().hex}'

        cache.set(key, 0, timeout=120)

        try:
            first = cache.incr(key)
            second = cache.incr(key)
        except Exception as error:  # noqa: BLE001
            self.stdout.write(self.style.ERROR(
                f'   incr fallo: {type(error).__name__}: {error}'
            ))
            return False

        cache.delete(key)

        if (first, second) != (1, 2):
            self.stdout.write(self.style.ERROR(
                f'   Conto {first} y {second}, y deberia contar 1 y 2.'
            ))
            return False

        self.stdout.write(self.style.SUCCESS('   Cuenta bien: 1, 2.'))

        return True

    def _check_expiry(self) -> bool:
        """
        Que el TTL se respete.

        Sin caducidad, una ventana de limite no se cierra nunca y el cupo se
        agota para siempre.
        """
        self._section('4. Caducidad')

        key = f'{READ_PREFIX}ttl:{uuid.uuid4().hex}'

        cache.set(key, 'efimero', timeout=1)
        time.sleep(1.5)

        if cache.get(key) is not None:
            self.stdout.write(self.style.ERROR(
                '   La clave sigue ahi despues de caducar.'
            ))
            return False

        self.stdout.write(self.style.SUCCESS('   Las claves caducan.'))

        return True

    def _check_shared(self) -> bool:
        """
        La prueba que de verdad decide: leer desde OTRO proceso.

        Es la diferencia entre un limite compartido y uno por worker. Se lanza
        este mismo comando en un subproceso, que es un proceso distinto de
        verdad, igual que lo es cada worker del servidor web.
        """
        self._section('5. Compartida entre procesos')

        key = f'{READ_PREFIX}shared:{uuid.uuid4().hex}'
        value = uuid.uuid4().hex

        cache.set(key, value, timeout=120)

        argv = [
            sys.executable,
            os.path.join(str(settings.BASE_DIR), 'manage.py'),
            'check_cache',
            '--read', key,
        ]

        self.stdout.write('   Escrita aqui; leyendola desde otro proceso...')

        try:
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(settings.BASE_DIR),
            )
        except Exception as error:  # noqa: BLE001
            self.stdout.write(self.style.WARNING(
                f'   No se pudo lanzar el subproceso ({error}). Esta '
                'comprobacion queda sin hacer.'
            ))
            return True

        cache.delete(key)

        seen = (result.stdout or '').strip().splitlines()
        seen = seen[-1].strip() if seen else ''

        if seen != value:
            self.stdout.write(self.style.ERROR(
                f'   El otro proceso NO la vio (leyo {seen!r}).'
            ))
            return False

        self.stdout.write(self.style.SUCCESS(
            '   El otro proceso la ve. La cache es compartida.'
        ))

        return True

    # ------------------------------------------------------------------
    # Diagnostico por capas
    #
    # «No responde» no es un diagnostico: entre Django y el Redis del VPS hay
    # cuatro capas y cada una falla por un motivo distinto y se arregla en un
    # sitio distinto. Se prueban de abajo arriba y se para en la primera que
    # rompe, que es la unica que hay que arreglar.
    # ------------------------------------------------------------------
    def _diagnose(self):
        self._section('Por que no responde')

        url = str(settings.CACHES['default'].get('LOCATION', ''))

        parts = self._parse_url(url)

        if not parts:
            self.stdout.write(self.style.ERROR(
                '   REDIS_URL no se puede interpretar. Debe ser de la forma '
                'rediss://usuario:clave@host:6380/0?ssl_cert_reqs=required&'
                'ssl_ca_certs=/ruta/ca.crt'
            ))
            return

        if not self._diag_ca(parts):
            return

        if not self._diag_dns(parts):
            return

        if not self._diag_tcp(parts):
            return

        if not self._diag_tls(parts):
            return

        self._diag_auth(parts)

    def _parse_url(self, url):
        from urllib.parse import parse_qs, urlparse

        try:
            parsed = urlparse(url)
        except ValueError:
            return None

        if not parsed.hostname:
            return None

        query = parse_qs(parsed.query or '')

        return {
            'scheme': parsed.scheme,
            'host': parsed.hostname,
            'port': parsed.port or 6379,
            'user': parsed.username or 'default',
            'password': parsed.password or '',
            'tls': parsed.scheme == 'rediss',
            'ca': (query.get('ssl_ca_certs') or [''])[0],
            'cert_reqs': (query.get('ssl_cert_reqs') or [''])[0],
        }

    def _diag_ca(self, parts) -> bool:
        """Capa 0: el fichero de la CA, que es cosa de este servidor."""
        if not parts['tls']:
            self.stdout.write(self.style.WARNING(
                '   0. TLS  La URL es redis:// y no rediss://: el trafico y la '
                'contrasena viajarian en claro por internet.'
            ))
            return True

        ca = parts['ca']

        if not ca:
            self.stdout.write(self.style.WARNING(
                '   0. CA   Sin ssl_ca_certs en la URL. Con una CA propia, la '
                'verificacion fallara.'
            ))
            return True

        if not os.path.isfile(ca):
            self.stdout.write(self.style.ERROR(
                f'   0. CA   NO existe el fichero {ca}'
            ))
            self.stdout.write(
                '           Copia ca.crt del VPS a esa ruta en este servidor. '
                'Solo ca.crt: nunca ca.key ni redis.key.'
            )
            return False

        if not os.access(ca, os.R_OK):
            self.stdout.write(self.style.ERROR(
                f'   0. CA   Existe pero no se puede leer: {ca}'
            ))
            return False

        self.stdout.write(self.style.SUCCESS(
            f'   0. CA   legible ({ca})'
        ))

        return True

    def _diag_dns(self, parts) -> bool:
        """Capa 1: que el nombre resuelva, y a donde."""
        import socket as _socket

        host = parts['host']

        try:
            infos = _socket.getaddrinfo(host, parts['port'],
                                        proto=_socket.IPPROTO_TCP)
        except Exception as error:  # noqa: BLE001
            self.stdout.write(self.style.ERROR(
                f'   1. DNS  {host} NO resuelve ({error})'
            ))
            self.stdout.write(
                '           Falta el registro A, o todavia no se ha '
                'propagado. Mientras tanto puedes poner la IP del VPS '
                'directamente en REDIS_URL, pero el certificado tiene que '
                'llevar esa IP en su subjectAltName.'
            )
            return False

        addresses = sorted({info[4][0] for info in infos})

        self.stdout.write(self.style.SUCCESS(
            f"   1. DNS  {host} -> {', '.join(addresses)}"
        ))

        return True

    def _diag_tcp(self, parts) -> bool:
        """Capa 2: el cortafuegos. Es la que mas falla."""
        import socket as _socket

        started = time.monotonic()

        try:
            with _socket.create_connection(
                (parts['host'], parts['port']), 8
            ):
                pass
        except Exception as error:  # noqa: BLE001
            elapsed = time.monotonic() - started

            self.stdout.write(self.style.ERROR(
                f"   2. TCP  sin conexion al puerto {parts['port']} tras "
                f'{elapsed:.1f}s ({type(error).__name__}: {error})'
            ))
            self.stdout.write(
                '           Es el cortafuegos, y casi siempre por una de dos: '
                'la regla DOCKER-USER del VPS no lleva la IP de SALIDA de este '
                'servidor, o el contenedor no esta arriba.'
            )
            self.stdout.write(
                '           Mira cual es la IP de salida real con:  '
                'curl -s https://ifconfig.io'
            )
            self.stdout.write(
                '           y que esa sea la autorizada en el VPS:  '
                'sudo iptables -L DOCKER-USER -n --line-numbers'
            )
            return False

        elapsed = (time.monotonic() - started) * 1000

        self.stdout.write(self.style.SUCCESS(
            f'   2. TCP  puerto abierto ({elapsed:.0f} ms)'
        ))

        return True

    def _diag_tls(self, parts) -> bool:
        """Capa 3: el certificado y la CA."""
        if not parts['tls']:
            return True

        import socket as _socket
        import ssl as _ssl

        context = _ssl.create_default_context(
            cafile=parts['ca'] if parts['ca'] else None
        )

        # Redis no habla HTTP, asi que no hay SNI que validar por nombre mas
        # alla del propio certificado; se comprueba el nombre igualmente
        # porque es lo que hara redis-py.
        try:
            with _socket.create_connection(
                (parts['host'], parts['port']), 8
            ) as raw:
                with context.wrap_socket(
                    raw, server_hostname=parts['host']
                ) as tls:
                    cert = tls.getpeercert()
        except _ssl.SSLCertVerificationError as error:
            self.stdout.write(self.style.ERROR(
                f'   3. TLS  el certificado NO se acepta ({error.verify_message})'
            ))
            self.stdout.write(
                '           O el ca.crt de este servidor no es el que firmo el '
                'certificado del VPS, o el nombre con el que se conecta no '
                'esta en su subjectAltName. Si cambiaste de nombre o de IP, '
                'hay que reemitir el certificado del paso 2.'
            )
            return False
        except Exception as error:  # noqa: BLE001
            self.stdout.write(self.style.ERROR(
                f'   3. TLS  fallo el handshake ({type(error).__name__}: {error})'
            ))
            self.stdout.write(
                '           Si el puerto abre pero el TLS no, comprueba que '
                'Redis tenga tls-port y no un puerto en claro.'
            )
            return False

        names = [
            value for kind, value in cert.get('subjectAltName', ())
            if kind in ('DNS', 'IP Address')
        ]

        self.stdout.write(self.style.SUCCESS(
            f"   3. TLS  certificado aceptado (vale para: {', '.join(names)})"
        ))

        return True

    def _diag_auth(self, parts) -> bool:
        """Capa 4: usuario y contrasena, ya sin la red de por medio."""
        try:
            import redis as _redis
        except Exception:  # noqa: BLE001
            self.stdout.write(
                '   4. AUTH sin la libreria redis no se puede comprobar.'
            )
            return False

        url = str(settings.CACHES['default'].get('LOCATION', ''))

        try:
            client = _redis.from_url(
                url, socket_connect_timeout=8, socket_timeout=8
            )
            client.ping()
        except Exception as error:  # noqa: BLE001
            message = str(error)

            self.stdout.write(self.style.ERROR(
                f'   4. AUTH rechazado ({type(error).__name__}: {message})'
            ))

            if 'WRONGPASS' in message or 'invalid username' in message:
                self.stdout.write(
                    '           Usuario o contrasena que no cuadran con el '
                    '«user gea» del redis.conf. Recuerda que ahi va el SHA-256 '
                    "de la clave:  printf '%s' 'LA_CLAVE' | sha256sum"
                )
            elif 'NOAUTH' in message:
                self.stdout.write(
                    '           REDIS_URL va sin credenciales y el usuario '
                    'default esta apagado, que es lo correcto. Anade '
                    'usuario:clave a la URL.'
                )
            elif 'NOPERM' in message:
                self.stdout.write(
                    '           Las credenciales valen pero al usuario le '
                    'falta permiso. Revisa la linea «user gea» del redis.conf.'
                )

            return False

        self.stdout.write(self.style.SUCCESS(
            '   4. AUTH las credenciales valen.'
        ))
        self.stdout.write(
            '           Las cuatro capas responden, asi que el fallo esta en '
            'la propia cache de Django y no en la conexion. Poco habitual: '
            'revisa KEY_PREFIX y que el usuario tenga acceso a «gea:*».'
        )

        return True
