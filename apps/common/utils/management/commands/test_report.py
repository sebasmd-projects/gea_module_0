# apps/common/utils/management/commands/test_report.py
"""
Ejecuta la suite y deja un informe que se pueda leer sin haber mirado.

``manage.py test`` imprime puntos y un número. Sirve para saber si algo está
roto, no para saber **qué** está flojo: qué app tiene menos pruebas, cuáles son
las diez más lentas, dónde no llega la cobertura. Ese dato existe mientras
corre la suite y se tira al terminar. Este comando lo recoge.

Por qué un subproceso, y no ``call_command``
--------------------------------------------
Dos motivos independientes, y cada uno bastaría:

* **La cobertura tiene que arrancar antes que Django.** ``coverage`` cuenta
  líneas ejecutadas desde que se instala el trazador; los módulos que se
  importaron antes ya se ejecutaron y salen como no cubiertos. Si se arranca
  desde dentro de un comando, medio proyecto está importado. Medido en
  proceso, el informe no es conservador: es falso.
* **La suite necesita otros ajustes.** ``settings_test`` usa SQLite en
  memoria porque el usuario de MySQL en cPanel no puede crear la base
  ``test_``. Los ajustes se leen una vez por proceso.

Y hay un tercero práctico: así el comando se comporta igual lanzado a mano que
desde la consola de operaciones, que ya ejecuta en subproceso por
``ATOMIC_REQUESTS``.

La cobertura es opcional
------------------------
``coverage`` no está en ``requirements.txt``: es una herramienta de desarrollo
y el servidor no la necesita. Si no está instalada, el comando no falla — hace
el informe de resultados y dice que la cobertura no se midió. Exigirla
convertiría una herramienta de diagnóstico en una dependencia de producción.

    manage.py test_report                      # con cobertura, si la hay
    manage.py test_report --no-coverage        # solo resultados, más rápido
    manage.py test_report --html               # además el HTML navegable
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from ...test_runner import (ERRORED, EXPECTED, FAILED, PASSED, REPORT_ENV,
                            SKIPPED)

#: Dónde se dejan los informes, bajo ``MEDIA_ROOT``. Van ahí y no en el
#: repositorio porque son salida, no código: en el servidor el árbol del
#: repositorio lo reescribe el siguiente ``git pull``.
REPORTS_DIR = 'test_reports'

#: El último, con nombre fijo, para que la página del resumen no tenga que
#: adivinar cuál es el más reciente listando el directorio.
LATEST = 'latest.json'

#: Cuántos informes se conservan. Son ficheros pequeños, pero un directorio
#: que sólo crece acaba siendo un problema de otro.
KEEP_DEFAULT = 20

#: El corredor que sabe tomar notas.
RUNNER = 'apps.common.utils.test_runner.JSONReportRunner'

#: Con qué ajustes corre la suite. Va fijo y no como opción: con los de
#: producción, las pruebas intentarían crear la base ``test_`` en MySQL.
TEST_SETTINGS = 'app_core.settings_test'

#: Qué mide la cobertura: el código del proyecto y nada más. Con ``.`` entran
#: el entorno virtual y Django entero, y un porcentaje que incluye a Django no
#: dice nada de este proyecto.
COVERAGE_SOURCE = 'apps,app_core'

#: Lo que se descuenta, y esto sí cambia la cifra de arriba abajo.
#:
#: * **Las propias pruebas.** Un fichero de pruebas se ejecuta entero por
#:   definición, así que contarlo sube la cobertura justo por escribir más
#:   pruebas de lo mismo. Medido con ellas dentro, este proyecto daba un 76%;
#:   sin ellas, la cifra es la de verdad. Un número que se infla solo es peor
#:   que ninguno, porque se usa para decidir dónde no hace falta mirar.
#: * **Las migraciones.** Son un histórico: la mayoría no se vuelve a
#:   ejecutar nunca y no hay nada que probar en ellas.
COVERAGE_OMIT = ','.join((
    '*/tests/*',
    '*/tests.py',
    '*/migrations/*',
    '*/settings_test.py',
))


def _timeout_for(seconds):
    """Ninguno cuando no se pidió, que es lo que quiere decir «sin prisa»."""
    return seconds or None


class Command(BaseCommand):
    help = (
        'Ejecuta la suite en un subproceso y escribe un informe con el '
        'resultado de cada prueba, los tiempos y, si coverage esta '
        'instalado, la cobertura por app.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--no-coverage', action='store_true',
            help=(
                'No mide la cobertura aunque coverage este instalado. La '
                'suite corre bastante mas rapida.'
            ),
        )
        parser.add_argument(
            '--html', action='store_true',
            help=(
                'Ademas del informe, genera el HTML navegable de coverage en '
                'htmlcov/. Es lo que se mira para ver que linea falta.'
            ),
        )
        parser.add_argument(
            '--keep', type=int, default=KEEP_DEFAULT,
            help=f'Cuantos informes anteriores se conservan (por defecto '
                 f'{KEEP_DEFAULT}).',
        )
        parser.add_argument(
            '--label', action='append', default=[],
            help=(
                'Limita la ejecucion a estas rutas de pruebas, igual que '
                'manage.py test. Se puede repetir.'
            ),
        )
        parser.add_argument(
            '--timeout', type=int, default=0,
            help='Segundos antes de cortar la ejecucion. 0 = sin limite.',
        )

    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        directory = self._reports_dir()
        stamp = timezone.now()
        target = directory / f'{stamp:%Y%m%d-%H%M%S}.json'

        with_coverage = not options['no_coverage'] and self._has_coverage()

        if not options['no_coverage'] and not with_coverage:
            self.stdout.write(self.style.WARNING(
                'coverage no esta instalado: se mide el resultado pero no la '
                'cobertura.  uv add coverage'
            ))

        started = time.time()
        code = self._run_suite(target, options, with_coverage)
        elapsed = round(time.time() - started, 1)

        report = self._load(target)

        if report is None:
            self.stderr.write(self.style.ERROR(
                f'La suite termino con codigo {code} pero no dejo informe. '
                f'Suele significar que reviento antes de empezar a ejecutar '
                f'pruebas: mira la salida de arriba.'
            ))
            return

        report['exit_code'] = code
        report['wall_seconds'] = elapsed
        report['label'] = ' '.join(options['label']) or 'toda la suite'
        report['settings'] = TEST_SETTINGS
        report['python'] = sys.version.split()[0]
        report['platform'] = sys.platform
        report['created'] = stamp.isoformat()

        if with_coverage:
            report['coverage'] = self._coverage(options['html'])
        else:
            report['coverage'] = None

        self._store(directory, target, report, options['keep'])
        self._print(report)

    # -- ejecucion ------------------------------------------------------
    def _run_suite(self, target, options, with_coverage) -> int:
        """
        Lanza la suite. Devuelve el codigo de salida del subproceso.

        La salida **no** se captura: se hereda. Una suite de diez minutos que
        no imprime nada hasta el final parece colgada, y en la consola de
        operaciones la salida se recoge igual porque la recoge el runner de
        ops, un nivel mas arriba.
        """
        manage = Path(settings.BASE_DIR) / 'manage.py'

        argv = [sys.executable]

        if with_coverage:
            # `-m coverage` y no el ejecutable `coverage`: asi se usa el del
            # entorno virtual que esta ejecutando esto, sin depender del PATH.
            argv += ['-m', 'coverage', 'run',
                     f'--source={COVERAGE_SOURCE}',
                     f'--omit={COVERAGE_OMIT}']

        argv += [
            str(manage), 'test',
            f'--settings={TEST_SETTINGS}',
            f'--testrunner={RUNNER}',
        ]
        argv += list(options['label'])

        env = dict(os.environ)
        env[REPORT_ENV] = str(target)
        # Sin esto, la salida de la suite sale con la codificacion de la
        # consola --cp1252 en Windows-- y un nombre de prueba con tilde corta
        # la ejecucion con un UnicodeEncodeError que no tiene nada que ver con
        # lo que se estaba probando.
        env['PYTHONIOENCODING'] = 'utf-8'

        # Se imprime la invocacion entera, con la ruta del interprete: cuando
        # algo sale raro, la pregunta es casi siempre «que python es ese».
        self.stdout.write(self.style.MIGRATE_HEADING(' '.join(argv)))
        self.stdout.write('')

        try:
            completed = subprocess.run(
                argv, env=env, cwd=str(settings.BASE_DIR),
                timeout=_timeout_for(options['timeout']),
            )
        except subprocess.TimeoutExpired:
            self.stderr.write(self.style.ERROR(
                f'Cortado a los {options["timeout"]}s.'
            ))
            return 124

        return completed.returncode

    def _load(self, target):
        try:
            return json.loads(target.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None

    # -- cobertura ------------------------------------------------------
    def _has_coverage(self) -> bool:
        """Si el interprete que nos ejecuta tiene coverage a mano."""
        try:
            return subprocess.run(
                [sys.executable, '-m', 'coverage', '--version'],
                capture_output=True, timeout=30,
            ).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def _coverage(self, want_html):
        """
        Lee la cobertura y la agrega por app.

        Se pasa por ``coverage json`` en vez de importar la biblioteca: asi
        este comando no importa nada que pueda no estar instalado, y el
        formato JSON de coverage es estable desde la 5.0.
        """
        # El nombre importa: `.coverage.*` ya esta en .gitignore, asi que si
        # una ejecucion se corta y el fichero sobrevive al `finally`, no acaba
        # en un commit.
        raw = Path(settings.BASE_DIR) / '.coverage.report.json'

        try:
            done = subprocess.run(
                [sys.executable, '-m', 'coverage', 'json', '-o', str(raw)],
                capture_output=True, text=True, timeout=300,
                cwd=str(settings.BASE_DIR),
            )
        except (OSError, subprocess.SubprocessError) as error:
            self.stderr.write(self.style.WARNING(
                f'No se pudo leer la cobertura: {error}'))
            return None

        if done.returncode != 0:
            self.stderr.write(self.style.WARNING(
                f'coverage json fallo: {done.stderr.strip()[:300]}'))
            return None

        try:
            data = json.loads(raw.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
        finally:
            raw.unlink(missing_ok=True)

        if want_html:
            self._coverage_html()

        return {
            'total': round(
                data.get('totals', {}).get('percent_covered', 0.0), 1),
            'statements': data.get('totals', {}).get('num_statements', 0),
            'covered': data.get('totals', {}).get('covered_lines', 0),
            'apps': self._by_app(data.get('files', {})),
        }

    def _coverage_html(self):
        try:
            subprocess.run(
                [sys.executable, '-m', 'coverage', 'html'],
                capture_output=True, timeout=300, cwd=str(settings.BASE_DIR),
            )
        except (OSError, subprocess.SubprocessError):
            pass

    def _by_app(self, files):
        """
        Reparte los ficheros medidos entre las apps declaradas.

        El reparto sale de ``ALL_CUSTOM_APPS`` y no de partir la ruta por
        tramos: las apps estan a profundidades distintas
        (``apps.common.utils`` y ``apps.project.specific.internal.ops``), asi
        que cualquier regla por numero de tramos acierta en unas y falla en
        otras. Se comparan los prefijos de mas largo a mas corto para que
        ``.../internal/code_gen`` no caiga en ``.../internal``.
        """
        prefixes = sorted(
            [(app.replace('.', '/') + '/', app[len('apps.'):])
             for app in settings.ALL_CUSTOM_APPS]
            # `app_core` no es una app instalada, es la configuración del
            # proyecto: ajustes, URLconf, el admin propio. Tiene código real y
            # dejarlo en «otros» lo esconde justo donde vive el guardia del
            # panel.
            + [('app_core/', 'app_core')],
            key=lambda pair: -len(pair[0]),
        )

        buckets = {}

        for path, entry in files.items():
            # coverage escribe las rutas con el separador del sistema y
            # relativas al directorio desde el que se lanzo. En Windows eso es
            # `apps\common\utils\models.py`, que no empieza por ningun prefijo
            # de los de arriba.
            normalised = path.replace('\\', '/')

            if 'apps/' in normalised and not normalised.startswith('apps/'):
                normalised = normalised[normalised.index('apps/'):]

            app = next(
                (name for prefix, name in prefixes
                 if normalised.startswith(prefix)),
                'otros',
            )

            summary = entry.get('summary', {})
            bucket = buckets.setdefault(
                app, {'app': app, 'statements': 0, 'covered': 0, 'files': 0})
            bucket['statements'] += summary.get('num_statements', 0)
            bucket['covered'] += summary.get('covered_lines', 0)
            bucket['files'] += 1

        for bucket in buckets.values():
            bucket['percent'] = round(
                100.0 * bucket['covered'] / bucket['statements'], 1
            ) if bucket['statements'] else 0.0

        # Una app sin ninguna sentencia medible --solo `__init__.py` vacios--
        # saldria como 0%, que se lee como «sin cubrir» cuando lo cierto es
        # que no hay nada que cubrir. Una fila que miente es peor que ninguna.
        return sorted(
            (bucket for bucket in buckets.values() if bucket['statements']),
            key=lambda bucket: bucket['percent'],
        )

    # -- persistencia ---------------------------------------------------
    def _reports_dir(self) -> Path:
        directory = Path(settings.MEDIA_ROOT) / REPORTS_DIR
        directory.mkdir(parents=True, exist_ok=True)
        self._protect(directory)

        return directory

    def _protect(self, directory: Path):
        """
        Cerrar el directorio al servidor web.

        Un informe de pruebas lleva nombres de modulos, rutas del proyecto y
        la primera linea de cada traza: es un mapa del codigo servido en
        abierto. Cuelga de ``MEDIA_ROOT``, asi que sin esto se sirve solo.
        """
        guard = directory / '.htaccess'

        if guard.exists():
            return

        source = (Path(settings.BASE_DIR) / 'deploy'
                  / 'media-protected.htaccess')

        try:
            guard.write_bytes(source.read_bytes())
        except OSError:
            pass

    def _store(self, directory, target, report, keep):
        body = json.dumps(report, indent=2, ensure_ascii=False)

        target.write_text(body, encoding='utf-8')
        (directory / LATEST).write_text(body, encoding='utf-8')

        self._prune(directory, keep)

    def _prune(self, directory, keep):
        older = sorted(
            (path for path in directory.glob('*.json') if path.name != LATEST),
            reverse=True,
        )

        for path in older[max(keep, 1):]:
            try:
                path.unlink()
            except OSError:
                pass

    # -- salida ---------------------------------------------------------
    def _print(self, report):
        totals = report['totals']
        width = shutil.get_terminal_size((80, 20)).columns

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('Resumen'))
        self.stdout.write('-' * min(width, 72))

        line = (
            f'  {report["total"]} pruebas en {report["duration"]}s   '
            f'{totals[PASSED]} pasan   {totals[FAILED]} fallan   '
            f'{totals[ERRORED]} con error   {totals[SKIPPED]} saltadas'
        )

        if totals[EXPECTED]:
            line += f'   {totals[EXPECTED]} fallos esperados'

        red = totals[FAILED] + totals[ERRORED]
        self.stdout.write(
            self.style.ERROR(line) if red else self.style.SUCCESS(line))

        self._print_apps(report)
        self._print_slowest(report)
        self._print_red(report)
        self._print_coverage(report)

    def _print_apps(self, report):
        by_app = {}

        for test in report['tests']:
            bucket = by_app.setdefault(test['app'], {'total': 0, 'red': 0})
            bucket['total'] += 1

            if test['outcome'] in (FAILED, ERRORED):
                bucket['red'] += 1

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('Por app'))

        for app, bucket in sorted(by_app.items()):
            mark = f'  {bucket["red"]} en rojo' if bucket['red'] else ''
            self.stdout.write(f'  {bucket["total"]:>4}  {app}{mark}')

    def _print_slowest(self, report):
        slowest = sorted(
            report['tests'], key=lambda t: t['seconds'], reverse=True)[:10]

        if not slowest:
            return

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('Las diez mas lentas'))

        for test in slowest:
            self.stdout.write(f'  {test["seconds"]:>7.2f}s  {test["id"]}')

    def _print_red(self, report):
        red = [t for t in report['tests']
               if t['outcome'] in (FAILED, ERRORED)]

        if not red:
            return

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('Lo que no pasa'))

        for test in red:
            self.stdout.write(self.style.ERROR(f'  {test["id"]}'))
            self.stdout.write(f'      {test["detail"]}')

    def _print_coverage(self, report):
        coverage = report.get('coverage')

        if not coverage:
            return

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'Cobertura: {coverage["total"]}%  '
            f'({coverage["covered"]}/{coverage["statements"]} sentencias)'
        ))

        for bucket in coverage['apps']:
            self.stdout.write(
                f'  {bucket["percent"]:>5.1f}%  {bucket["app"]}  '
                f'({bucket["covered"]}/{bucket["statements"]})'
            )
