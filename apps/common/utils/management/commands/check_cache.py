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
                'tasa no se aplican. Revisa REDIS_URL, el cortafuegos del VPS '
                'y que el contenedor este arriba.'
            ))
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
        """Escribir y volver a leer, que es lo minimo."""
        self._section('2. Ida y vuelta')

        key = f'{READ_PREFIX}{uuid.uuid4().hex}'
        value = {'probe': key}

        started = time.monotonic()
        cache.set(key, value, timeout=120)
        read = cache.get(key)
        elapsed = (time.monotonic() - started) * 1000

        if read != value:
            self.stdout.write(self.style.ERROR(
                f'   Se escribio y volvio {read!r}. Con IGNORE_EXCEPTIONS un '
                'servidor inalcanzable devuelve None sin lanzar: eso es lo '
                'que parece haber pasado.'
            ))
            return False

        self.stdout.write(self.style.SUCCESS(
            f'   Escribe y lee correctamente ({elapsed:.0f} ms ida y vuelta).'
        ))

        if elapsed > 500:
            self.stdout.write(self.style.WARNING(
                '   Va lento. Cada peticion con limite de tasa paga esto, y '
                'con ATOMIC_REQUESTS se paga con una transaccion abierta.'
            ))

        cache.delete(key)

        return True

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
