# apps/project/specific/internal/ops/tests/test_summary.py
"""
Que el resumen de pruebas diga la verdad, y que no se vea donde no toca.

Un panel de metricas equivocado es peor que no tenerlo: se mira en vez de
mirar la suite, y decide donde se escriben las siguientes pruebas. Lo que se
fija aqui:

* un `skip` no suma a las verdes -- contarlo infla la cifra justo donde
  conviene no enganarse;
* las barras se miden contra la app mas grande, no contra el total;
* la pagina esta cerrada igual que el comando que la alimenta, y con 404.

    manage.py test apps.project.specific.internal.ops.tests.test_summary \\
        --settings=app_core.settings_test
"""

import json
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.common.utils.test_runner import (ERRORED, FAILED, PASSED, SKIPPED,
                                           EXPECTED)
from apps.common.utils.testing import login_with_otp
from apps.project.common.users.models import UserModel

from ..summary import LATEST, REPORTS_DIR, latest_report, shape

PASSWORD = 'pw-for-tests-123'


def a_test(name, app, outcome=PASSED, seconds=0.1, detail=''):
    return {
        'id': f'apps.{app}.tests.test_x.SomeTests.{name}',
        'app': app,
        'module': f'apps.{app}.tests.test_x',
        'outcome': outcome,
        'seconds': seconds,
        'detail': detail,
    }


def a_report(tests, **extra):
    totals = {
        name: sum(1 for test in tests if test['outcome'] == name)
        for name in (PASSED, FAILED, ERRORED, SKIPPED, EXPECTED)
    }

    report = {
        'total': len(tests),
        'totals': totals,
        'tests': tests,
        'duration': 1.0,
        'created': '2026-09-09T14:22:31',
        'python': '3.11.9',
        'platform': 'linux',
        'settings': 'app_core.settings_test',
        'label': 'toda la suite',
        'coverage': None,
    }
    report.update(extra)

    return report


class TheHeadlineFigureTests(TestCase):

    def test_a_skipped_test_does_not_count_as_green(self):
        """
        La confusion que infla el numero grande. Una prueba saltada no
        comprobo nada: sumarla a las verdes hace que la cifra suba cuando lo
        que ha pasado es que dejo de mirarse algo.
        """
        summary = shape(a_report([
            a_test('a', 'common.utils'),
            a_test('b', 'common.utils', SKIPPED),
        ]))

        self.assertEqual(summary['pass_rate'], 50.0)

    def test_an_expected_failure_does_count_as_green(self):
        """
        Al reves que la anterior, y por el mismo criterio: una prueba marcada
        como «se espera que falle» que falla comprobo exactamente lo que decia
        que iba a comprobar.
        """
        summary = shape(a_report([
            a_test('a', 'common.utils'),
            a_test('b', 'common.utils', EXPECTED),
        ]))

        self.assertEqual(summary['pass_rate'], 100.0)

    def test_failures_and_errors_are_both_red(self):
        summary = shape(a_report([
            a_test('a', 'common.utils', FAILED),
            a_test('b', 'common.utils', ERRORED),
            a_test('c', 'common.utils'),
        ]))

        self.assertEqual(summary['red'], 2)

    def test_an_empty_report_is_no_report(self):
        self.assertIsNone(shape(None))


class TheOutcomeRowsTests(TestCase):

    def test_an_outcome_that_did_not_happen_is_not_a_row(self):
        """
        Cinco filas de las que tres son cero no es un resumen, es una leyenda.
        """
        summary = shape(a_report([a_test('a', 'common.utils')]))

        self.assertEqual([row['key'] for row in summary['outcomes']],
                         [PASSED])

    def test_every_row_carries_its_own_icon_and_label(self):
        """
        En la paleta de estado el verde y el rojo se separan un delta E de 4
        bajo deuteranopia: para bastante gente son el mismo color. Sin icono y
        sin etiqueta, la grafica no dice cual es cual.
        """
        summary = shape(a_report([
            a_test('a', 'common.utils'),
            a_test('b', 'common.utils', FAILED),
        ]))

        for row in summary['outcomes']:
            self.assertTrue(row['icon'])
            self.assertTrue(str(row['label']))
            self.assertTrue(row['tone'])

    def test_the_percentages_are_of_the_whole_run(self):
        summary = shape(a_report([
            a_test('a', 'common.utils'),
            a_test('b', 'common.utils'),
            a_test('c', 'common.utils', FAILED),
            a_test('d', 'common.utils', SKIPPED),
        ]))

        percentages = {row['key']: row['percent'] for row in summary['outcomes']}

        self.assertEqual(percentages[PASSED], 50.0)
        self.assertEqual(percentages[FAILED], 25.0)


class TheAppRowsTests(TestCase):

    def setUp(self):
        self.summary = shape(a_report([
            a_test('a', 'common.utils'),
            a_test('b', 'common.utils'),
            a_test('c', 'common.utils', FAILED),
            a_test('d', 'common.utils', SKIPPED),
            a_test('e', 'project.common.users'),
        ]))
        self.rows = {row['app']: row for row in self.summary['apps']}

    def test_the_bars_are_measured_against_the_biggest_app(self):
        """
        Y no contra el total. Con 750 pruebas repartidas en trece apps, medir
        contra el total deja todas las barras pegadas al eje.
        """
        self.assertEqual(self.rows['common.utils']['width'], 100.0)
        self.assertEqual(self.rows['project.common.users']['width'], 25.0)

    def test_red_and_skipped_are_counted_apart(self):
        self.assertEqual(self.rows['common.utils']['red'], 1)
        self.assertEqual(self.rows['common.utils']['skipped'], 1)

    def test_the_biggest_comes_first(self):
        self.assertEqual(self.summary['apps'][0]['app'], 'common.utils')


class TheSlowestTests(TestCase):

    def test_only_ten_are_shown_and_the_slowest_leads(self):
        summary = shape(a_report([
            a_test(f'test_{index}', 'common.utils', seconds=index / 10)
            for index in range(30)
        ]))

        self.assertEqual(len(summary['slowest']), 10)
        self.assertEqual(summary['slowest'][0]['seconds'], 2.9)
        self.assertEqual(summary['slowest'][0]['width'], 100.0)

    def test_the_identifier_is_split_so_the_name_is_readable(self):
        """
        Puesto entero, la parte que distingue una fila de la siguiente queda
        al final de una linea de cien caracteres.
        """
        summary = shape(a_report([a_test('test_it_opens', 'common.utils')]))
        row = summary['slowest'][0]

        self.assertEqual(row['name'], 'test_it_opens')
        self.assertIn('common.utils', row['where'])


class TheFailureListTests(TestCase):

    def test_only_the_red_ones_are_listed_with_their_last_line(self):
        summary = shape(a_report([
            a_test('a', 'common.utils'),
            a_test('b', 'common.utils', FAILED, detail='AssertionError: no'),
            a_test('c', 'common.utils', SKIPPED, detail='a proposito'),
        ]))

        self.assertEqual(len(summary['failures']), 1)
        self.assertEqual(summary['failures'][0]['detail'],
                         'AssertionError: no')


class TheReportOnDiskTests(TestCase):

    def test_without_a_file_there_is_no_report(self):
        with tempfile.TemporaryDirectory() as directory:
            with override_settings(MEDIA_ROOT=directory):
                self.assertIsNone(latest_report())

    def test_a_broken_file_is_not_a_crash(self):
        """
        Un informe a medias --el comando cortado a mitad de escribir-- no
        puede tumbar la pagina: se comporta como si no hubiera ninguno.
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / REPORTS_DIR
            path.mkdir()
            (path / LATEST).write_text('{"tests": [', encoding='utf-8')

            with override_settings(MEDIA_ROOT=directory):
                self.assertIsNone(latest_report())

    def test_the_newest_is_read_by_a_fixed_name(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / REPORTS_DIR
            path.mkdir()
            (path / LATEST).write_text(
                json.dumps(a_report([a_test('a', 'common.utils')])),
                encoding='utf-8')

            with override_settings(MEDIA_ROOT=directory):
                self.assertEqual(latest_report()['total'], 1)


class ThePageTests(TestCase):
    """Quien la ve, donde, y que se ve cuando todavia no hay nada."""

    @classmethod
    def setUpTestData(cls):
        cls.superuser = UserModel.objects.create_superuser(
            username='sum_root', email='sumroot@example.com',
            password=PASSWORD,
        )
        cls.staff = UserModel.objects.create_user(
            username='sum_staff', email='sumstaff@example.com',
            password=PASSWORD,
            user_type=UserModel.UserTypeChoices.BUYER, is_staff=True,
        )

    def setUp(self):
        self.url = reverse('admin:ops_test_summary')

    @override_settings(DEBUG=True)
    def test_a_superuser_sees_it_in_development(self):
        login_with_otp(self.client, self.superuser)

        self.assertEqual(self.client.get(self.url).status_code, 200)

    @override_settings(DEBUG=True)
    def test_staff_does_not(self):
        """
        Igual que el resto de la consola: staff no basta, y la respuesta es
        404. Un 403 confirmaria que la ruta existe.
        """
        login_with_otp(self.client, self.staff)

        self.assertEqual(self.client.get(self.url).status_code, 404)

    @override_settings(DEBUG=False)
    def test_in_production_it_is_a_404(self):
        """
        Cerrada como el comando que la alimenta. Alli no hay --ni puede
        haber-- un informe recien hecho: la suite se ejecuta con
        `settings_test` porque el usuario de MySQL en cPanel no puede crear la
        base `test_`. Lo que se veria seria el de un portatil, con la fecha en
        letra pequena y la cifra grande, leida como el estado del servidor.
        """
        login_with_otp(self.client, self.superuser)

        self.assertEqual(self.client.get(self.url).status_code, 404)

    @override_settings(DEBUG=True)
    def test_without_a_report_it_says_how_to_make_one(self):
        login_with_otp(self.client, self.superuser)

        with tempfile.TemporaryDirectory() as directory:
            with override_settings(MEDIA_ROOT=directory):
                response = self.client.get(self.url)

        self.assertContains(response, 'test_report')

    @override_settings(DEBUG=True)
    def test_with_a_report_the_numbers_are_on_the_page(self):
        login_with_otp(self.client, self.superuser)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / REPORTS_DIR
            path.mkdir()
            (path / LATEST).write_text(json.dumps(a_report([
                a_test('a', 'common.utils'),
                a_test('b', 'common.utils', FAILED,
                       detail='AssertionError: la prueba que no pasa'),
            ])), encoding='utf-8')

            with override_settings(MEDIA_ROOT=directory):
                response = self.client.get(self.url)

        self.assertContains(response, 'common.utils')
        self.assertContains(response, 'la prueba que no pasa')

    @override_settings(DEBUG=True)
    def test_every_chart_has_a_table_beside_it(self):
        """
        Una barra que solo se lee pasando el raton no se lee con el teclado,
        ni se copia, ni se imprime.
        """
        login_with_otp(self.client, self.superuser)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / REPORTS_DIR
            path.mkdir()
            (path / LATEST).write_text(json.dumps(a_report(
                [a_test('a', 'common.utils')],
                coverage={'total': 50.0, 'covered': 5, 'statements': 10,
                          'apps': [{'app': 'common.utils', 'percent': 50.0,
                                    'covered': 5, 'statements': 10}]},
            )), encoding='utf-8')

            with override_settings(MEDIA_ROOT=directory):
                response = self.client.get(self.url)

        body = response.content.decode()

        for table in ('t-apps', 't-cov', 't-slow'):
            self.assertIn(f'id="{table}"', body)

    @override_settings(DEBUG=True)
    def test_without_coverage_it_says_so_instead_of_showing_zero(self):
        """
        Cero por ciento y «no se midio» son cosas distintas, y la segunda es
        la que hay cuando coverage no esta instalado. Pintarlo como cero
        diria que el proyecto no tiene pruebas.
        """
        login_with_otp(self.client, self.superuser)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / REPORTS_DIR
            path.mkdir()
            (path / LATEST).write_text(
                json.dumps(a_report([a_test('a', 'common.utils')])),
                encoding='utf-8')

            with override_settings(MEDIA_ROOT=directory):
                response = self.client.get(self.url)

        self.assertContains(response, 'uv add coverage')

    @override_settings(DEBUG=True)
    def test_the_console_links_to_it_in_development(self):
        login_with_otp(self.client, self.superuser)

        response = self.client.get(reverse('admin:ops_console'))

        self.assertContains(response, self.url)

    @override_settings(DEBUG=False)
    def test_the_console_does_not_link_to_a_404(self):
        """
        Un enlace que lleva a un 404 no es una pista util: es una pista de que
        hay algo ahi.
        """
        login_with_otp(self.client, self.superuser)

        response = self.client.get(reverse('admin:ops_console'))

        self.assertNotContains(response, self.url)
