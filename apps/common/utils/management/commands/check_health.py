# apps/common/utils/management/commands/check_health.py
"""
El health check, desde dentro y desde fuera.

``/health/`` ya existe y comprueba base de datos, cache y correo. Lo que
faltaba era poder mirarlo sin abrir el navegador y, sobre todo, poder
comparar las dos formas de preguntarlo, porque no responden lo mismo:

* **Desde dentro** (``--local``, lo que se hace por defecto) se ejecutan las
  comprobaciones en este proceso. Dice si la aplicacion alcanza la base de
  datos, el Redis y el servidor de correo.

* **Desde fuera** (``--http``) se pide la URL publica de verdad. Eso ademas
  atraviesa el servidor web, el certificado y el DNS.

La diferencia es el diagnostico. Si el local va bien y el HTTP no, el problema
no esta en la aplicacion sino delante de ella -- y ahi no hay nada que buscar
en el codigo. Es la misma URL que golpea la tarea de calentamiento cada tres
minutos.

    manage.py check_health
    manage.py check_health --http
"""

import json
import urllib.error
import urllib.request

import django
from django.conf import settings
from django.core.management.base import BaseCommand

from ...outbound import InsecureUrlScheme, require_http_url

DEFAULT_TIMEOUT = 15


class Command(BaseCommand):
    help = 'Comprueba la salud de la aplicacion: base de datos, cache y correo.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--http',
            action='store_true',
            help='Pedir la URL publica en vez de comprobarlo en el proceso.',
        )
        parser.add_argument(
            '--timeout',
            type=int,
            default=DEFAULT_TIMEOUT,
            help='Segundos de espera de la peticion HTTP.',
        )

    def handle(self, *args, **options):
        if options['http']:
            return self._over_http(options['timeout'])

        return self._in_process()

    # ------------------------------------------------------------------
    def _in_process(self):
        """
        Las mismas comprobaciones que la vista, en este proceso.

        Se reutiliza la vista en lugar de reescribirlas: dos versiones de la
        misma comprobacion acaban discrepando, y entonces no se sabe cual
        creer.
        """
        from apps.common.core.views import HealthCheckView

        view = HealthCheckView()

        checks = {
            'database': view._check_database(),
            'cache': view._check_cache(),
            'email': view._check_email(),
        }

        self.stdout.write('Comprobado dentro del proceso de la aplicacion.')
        self.stdout.write('')

        self._database_version()

        return self._report(checks)

    # ------------------------------------------------------------------
    def _database_version(self) -> None:
        """
        Que version del motor hay al otro lado, y si a Django le vale.

        Cada version de Django sube el minimo del motor --5.2 pide MySQL
        8.0.11, MariaDB 10.5 o PostgreSQL 14-- y cuando no se cumple **no
        arranca**: levanta `NotSupportedError` al conectar. Eso convierte una
        actualizacion de Django en una sorpresa el dia del despliegue, que es
        el peor momento para descubrir que el hosting va por detras.

        Los numeros no se escriben aqui: se preguntan a Django
        (`features.minimum_database_version`), porque escribirlos seria
        garantizar que se quedan viejos justo en la siguiente actualizacion.

        Nunca falla la comprobacion: si el motor no contesta la version, lo
        dice y sigue. Lo que de verdad prueba la conexion es la comprobacion
        `database`, que ya esta arriba.
        """
        from django.db import connection

        try:
            version = connection.get_database_version()
        except Exception as error:                      # noqa: BLE001
            self.stdout.write(
                f'  Motor: {connection.display_name} — no dice su version '
                f'({error.__class__.__name__}).'
            )
            self.stdout.write('')
            return

        minimum = getattr(connection.features, 'minimum_database_version', None)

        legible = '.'.join(str(part) for part in version)
        line = f'  Motor: {connection.display_name} {legible}'

        if minimum:
            line += f' (Django {django.get_version()} pide '
            line += '.'.join(str(part) for part in minimum) + ')'

        if minimum and tuple(version) < tuple(minimum):
            # A este punto no se llega con Django ya conectado: el propio
            # `connection` aborta antes. Se deja por si algun dia la
            # comprobacion de Django cambia de momento, y para que la razon
            # este escrita donde se lee.
            self.stdout.write(self.style.ERROR(line + '  ← POR DEBAJO'))
        else:
            self.stdout.write(self.style.SUCCESS(line))

        self.stdout.write('')

    def _over_http(self, timeout):
        url = self._health_url()

        self.stdout.write(f'Pidiendo {url}')
        self.stdout.write('')

        # `urlopen` abre tambien `file://`, y esta URL sale de la
        # configuracion (`GEA_WARMUP_URL` o `PUBLIC_BASE_URL`). Se comprueba el
        # esquema antes de abrirla; ver apps/common/utils/outbound.py.
        #
        # Se sale con codigo distinto de cero, como el resto de fallos de esta
        # ruta: una URL mal configurada no es "todo bien", es que la
        # comprobacion no se ha podido hacer.
        try:
            require_http_url(url)
        except InsecureUrlScheme as error:
            self.stderr.write(self.style.ERROR(str(error)))
            raise SystemExit(1)

        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                status = response.status
                body = response.read().decode('utf-8', errors='replace')
        except urllib.error.HTTPError as error:
            # Un 503 es una respuesta valida del health check, no un fallo de
            # la peticion: lleva dentro que comprobacion no paso.
            status = error.code
            body = error.read().decode('utf-8', errors='replace')
        except (urllib.error.URLError, OSError) as error:
            self.stderr.write(self.style.ERROR(
                f'No se pudo alcanzar la URL: {error}'
            ))
            self.stdout.write(
                'Si la comprobacion local si pasa, el problema esta delante '
                'de la aplicacion: servidor web, DNS o certificado.'
            )
            raise SystemExit(1)

        try:
            data = json.loads(body)
        except ValueError:
            self.stderr.write(self.style.ERROR(
                f'Respuesta {status}, pero no es JSON:'
            ))
            self.stdout.write(body[:2000])
            raise SystemExit(1)

        self.stdout.write(f'HTTP {status} — {data.get("response", "?")}')
        self.stdout.write('')

        return self._report(data.get('checks') or {})

    # ------------------------------------------------------------------
    def _health_url(self) -> str:
        """
        La URL publica, nunca derivada de una peticion.

        Se prefiere la de calentamiento porque es exactamente la que ya se
        golpea cada tres minutos: comprobar otra distinta comprobaria otra
        cosa.
        """
        from django.urls import reverse

        warmup = getattr(settings, 'GEA_WARMUP_URL', '')

        if warmup:
            return warmup

        base = (getattr(settings, 'PUBLIC_BASE_URL', '') or '').rstrip('/')

        return f'{base}{reverse("core:health_check")}'

    def _report(self, checks: dict):
        if not checks:
            self.stderr.write(self.style.ERROR('Sin comprobaciones.'))
            raise SystemExit(1)

        failed = []

        for name, result in checks.items():
            ok = bool(result.get('ok'))
            mark = 'OK  ' if ok else 'FALLA'
            detail = result.get('detail', '')

            line = f'  [{mark}] {name:<10} {detail}'

            if ok:
                self.stdout.write(self.style.SUCCESS(line))
            else:
                self.stdout.write(self.style.ERROR(line))
                failed.append(name)

        self.stdout.write('')

        if failed:
            self.stdout.write(self.style.ERROR(
                f'No pasan: {", ".join(failed)}.'
            ))
            # Codigo distinto de cero: la consola lo marca como fallido y no
            # hay que leerse la salida para saber que algo va mal.
            raise SystemExit(1)

        self.stdout.write(self.style.SUCCESS('Todo responde.'))
