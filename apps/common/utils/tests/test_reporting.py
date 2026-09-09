# apps/common/utils/tests/test_reporting.py
"""
Que el resumen de pruebas cuente lo que pasó, y no otra cosa.

Un informe de pruebas equivocado es peor que no tenerlo: se mira en vez de
mirar la suite, y decide dónde se escriben las siguientes. Las trampas que se
cubren aquí son las tres que lo harían mentir sin fallar:

* que una prueba saltada se cuente como que pasa,
* que la cobertura de una app profunda caiga en la de su padre
  (``.../internal/code_gen`` dentro de ``.../internal``),
* que el informe se escriba solo, sin que nadie lo pida, y quede un fichero
  suelto en cada ejecución de la suite.

    manage.py test apps.common.utils.tests.test_reporting \\
        --settings=app_core.settings_test
"""

import json
import os
import tempfile
import unittest
from io import StringIO
from pathlib import Path

from django.test import SimpleTestCase, override_settings

from ..management.commands import test_report as reporting
from ..test_runner import (ERRORED, EXPECTED, FAILED, PASSED, REPORT_ENV,
                           SKIPPED, JSONReportRunner, RecordingResult, app_of)


def sample_case():
    """
    Un caso de cada desenlace, para que haya algo que contar.

    Se construye **dentro de una función** y no a nivel de módulo a propósito:
    el descubrimiento de ``unittest`` recorre este fichero y cargaría estas
    cinco pruebas como si fueran de verdad. La suite entera saldría en rojo,
    con un fallo y un error deliberados que no significan nada.
    """

    class Sample(unittest.TestCase):

        def test_it_passes(self):
            self.assertTrue(True)

        def test_it_fails(self):
            self.fail('a proposito')

        def test_it_breaks(self):
            raise RuntimeError('a proposito')

        @unittest.skip('a proposito')
        def test_it_is_skipped(self):
            pass

        @unittest.expectedFailure
        def test_it_is_expected_to_fail(self):
            self.fail('a proposito')

    return Sample


def run_sample():
    """Ejecuta el caso de arriba con el resultado que toma notas."""
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(sample_case())
    result = RecordingResult(StringIO(), True, 0)

    suite.run(result)

    return result


class TheOutcomesAreCountedApartTests(SimpleTestCase):

    def setUp(self):
        self.records = {
            record['id'].rsplit('.', 1)[-1]: record
            for record in run_sample().records
        }

    def test_each_ending_gets_its_own_name(self):
        self.assertEqual(self.records['test_it_passes']['outcome'], PASSED)
        self.assertEqual(self.records['test_it_fails']['outcome'], FAILED)
        self.assertEqual(self.records['test_it_breaks']['outcome'], ERRORED)
        self.assertEqual(
            self.records['test_it_is_skipped']['outcome'], SKIPPED)
        self.assertEqual(
            self.records['test_it_is_expected_to_fail']['outcome'], EXPECTED)

    def test_a_skipped_test_is_not_a_passing_test(self):
        """
        La confusion que infla un resumen justo donde conviene no enganarse:
        una prueba saltada no comprobo nada, asi que sumarla a las verdes hace
        que la barra suba cuando lo que ha pasado es que dejo de mirarse algo.
        """
        self.assertNotEqual(
            self.records['test_it_is_skipped']['outcome'], PASSED)

    def test_the_reason_of_a_skip_is_kept(self):
        self.assertIn('a proposito', self.records['test_it_is_skipped']['detail'])

    def test_a_failure_keeps_something_to_read(self):
        self.assertTrue(self.records['test_it_fails']['detail'])

    def test_the_detail_never_grows_into_a_whole_traceback(self):
        """
        Una traza entera por prueba convierte el informe en megabytes. Para el
        resumen basta la ultima linea; la traza sigue en la salida del corredor.
        """
        for record in self.records.values():
            self.assertLessEqual(len(record['detail']), 300)

    def test_every_test_is_timed(self):
        for record in self.records.values():
            self.assertIsInstance(record['seconds'], float)


class TheAppOfATestTests(SimpleTestCase):

    def test_it_is_read_from_the_module_path(self):
        self.assertEqual(
            app_of(_fake('apps.common.utils.tests.test_backup')),
            'common.utils')

    def test_it_cuts_at_the_tests_package_however_deep_the_app_is(self):
        self.assertEqual(
            app_of(_fake(
                'apps.project.specific.internal.code_gen.tests.test_jcs')),
            'project.specific.internal.code_gen')

    def test_something_outside_apps_still_gets_a_name(self):
        self.assertEqual(app_of(_fake('')), 'sin app')


def _fake(module):
    """Lo minimo que ``app_of`` mira de una prueba."""
    return type('Fake', (), {'__module__': module})()


class TheReportIsOnlyWrittenWhenAskedTests(SimpleTestCase):
    """
    El corredor no es el de por defecto y aun asi puede acabar siendolo por un
    ajuste. Si escribiera siempre, cada ejecucion de la suite dejaria un
    fichero suelto donde apuntara la variable de la vez anterior.

    Ojo con lo que hay debajo: estas pruebas tocan la MISMA variable de
    entorno que el corredor que las esta ejecutando. Quitarla y no devolverla
    hace que la suite entera termine en verde y sin informe --paso-- y ademas
    no se ve ejecutando este fichero solo, porque ahi no hay informe que
    escribir. De ahi `_take_over`, y de ahi tambien que el corredor lea el
    destino al construirse y no al escribir.
    """

    def _take_over(self, value):
        """Toma la variable durante la prueba y la devuelve como estaba."""
        previous = os.environ.get(REPORT_ENV)

        def restore():
            if previous is None:
                os.environ.pop(REPORT_ENV, None)
            else:
                os.environ[REPORT_ENV] = previous

        self.addCleanup(restore)

        if value is None:
            os.environ.pop(REPORT_ENV, None)
        else:
            os.environ[REPORT_ENV] = value

    def test_without_the_variable_nothing_is_written(self):
        self._take_over(None)

        with tempfile.TemporaryDirectory() as directory:
            runner = JSONReportRunner()
            runner._write_report(run_sample(), 0.0)

            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_with_the_variable_the_totals_add_up(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'sub' / 'informe.json'
            self._take_over(str(target))

            runner = JSONReportRunner()
            runner._write_report(run_sample(), 0.0)

            payload = json.loads(target.read_text(encoding='utf-8'))

        self.assertEqual(payload['total'], 5)
        self.assertEqual(sum(payload['totals'].values()), payload['total'])
        self.assertEqual(payload['totals'][PASSED], 1)
        self.assertEqual(payload['totals'][FAILED], 1)

    def test_the_destination_is_read_before_the_suite_runs(self):
        """
        La regla que hace que lo de arriba no pueda repetirse: el corredor fija
        el destino al construirse. Una prueba que cambie la variable a mitad de
        la suite --y las hay legitimas-- ya no puede desviar el informe.
        """
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'el-bueno.json'
            self._take_over(str(target))

            runner = JSONReportRunner()

            # Una prueba cualquiera, a mitad de la suite, se lleva la variable.
            os.environ.pop(REPORT_ENV, None)

            runner._write_report(run_sample(), 0.0)

            self.assertTrue(target.exists())


APPS = [
    'apps.common.utils',
    'apps.project.specific.internal.ops',
    'apps.project.specific.internal.code_gen',
]


class TheCoverageIsSplitByAppTests(SimpleTestCase):

    def setUp(self):
        self.command = reporting.Command()

    @override_settings(ALL_CUSTOM_APPS=APPS)
    def test_a_deep_app_does_not_fall_into_its_parent(self):
        """
        La trampa concreta: las apps estan a profundidades distintas, asi que
        partir la ruta por numero de tramos acierta en unas y falla en otras.
        Se comparan prefijos de mas largo a mas corto.
        """
        buckets = self._buckets({
            'apps/project/specific/internal/code_gen/services/jcs.py':
                _summary(100, 90),
            'apps/project/specific/internal/ops/registry.py':
                _summary(200, 200),
        })

        self.assertEqual(
            buckets['project.specific.internal.code_gen']['percent'], 90.0)
        self.assertEqual(
            buckets['project.specific.internal.ops']['percent'], 100.0)

    @override_settings(ALL_CUSTOM_APPS=APPS)
    def test_windows_separators_land_in_the_same_bucket(self):
        """
        Coverage escribe las rutas con el separador del sistema. Sin
        normalizar, en un portatil Windows toda la cobertura caeria en «otros»
        y el informe diria que el proyecto no tiene ninguna.
        """
        buckets = self._buckets({
            r'apps\common\utils\models.py': _summary(50, 25),
        })

        self.assertEqual(buckets['common.utils']['percent'], 50.0)

    @override_settings(ALL_CUSTOM_APPS=APPS)
    def test_a_file_outside_the_apps_is_not_silently_attributed(self):
        buckets = self._buckets({'manage.py': _summary(10, 10)})

        self.assertIn('otros', buckets)

    @override_settings(ALL_CUSTOM_APPS=APPS)
    def test_an_app_with_nothing_to_measure_is_left_out(self):
        """
        Una app que solo tiene `__init__.py` vacios saldria al 0%, que se lee
        como «sin cubrir» cuando lo cierto es que no hay nada que cubrir. Una
        fila que miente es peor que ninguna fila.
        """
        buckets = self._buckets({
            'apps/common/utils/__init__.py': _summary(0, 0),
            'apps/project/specific/internal/ops/registry.py':
                _summary(10, 10),
        })

        self.assertNotIn('common.utils', buckets)

    def _buckets(self, files):
        return {bucket['app']: bucket
                for bucket in self.command._by_app(files)}


def _summary(statements, covered):
    return {'summary': {'num_statements': statements,
                        'covered_lines': covered}}


class TheReportsDirectoryTests(SimpleTestCase):

    def setUp(self):
        self.command = reporting.Command()

    def test_only_the_newest_are_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)

            for day in range(1, 8):
                (path / f'2026010{day}-120000.json').write_text(
                    '{}', encoding='utf-8')

            (path / reporting.LATEST).write_text('{}', encoding='utf-8')

            self.command._prune(path, keep=3)

            left = sorted(item.name for item in path.glob('*.json'))

        self.assertEqual(left, [
            '20260105-120000.json',
            '20260106-120000.json',
            '20260107-120000.json',
            reporting.LATEST,
        ])

    def test_the_pointer_to_the_newest_is_never_pruned(self):
        """
        La pagina del resumen lee `latest.json` por nombre fijo. Si la poda se
        lo llevara, la pagina quedaria en blanco justo despues de la
        ejecucion que la tenia que llenar.
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / reporting.LATEST).write_text('{}', encoding='utf-8')

            self.command._prune(path, keep=1)

            self.assertTrue((path / reporting.LATEST).exists())

    def test_the_directory_is_closed_to_the_web(self):
        """
        Un informe lleva nombres de modulos, rutas del proyecto y la primera
        linea de cada traza: es un mapa del codigo. Cuelga de MEDIA_ROOT, asi
        que sin el .htaccess se sirve solo.
        """
        with tempfile.TemporaryDirectory() as directory:
            with override_settings(MEDIA_ROOT=directory):
                created = self.command._reports_dir()

            self.assertTrue((created / '.htaccess').exists())
            self.assertIn(
                'denied',
                (created / '.htaccess').read_text(encoding='utf-8').lower())
