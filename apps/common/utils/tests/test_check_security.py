# apps/common/utils/tests/test_check_security.py
"""
Que `check_security` diga la verdad en el servidor y en local.

Dos cosas que ya salieron mal, y que el informe de un servidor real dejo a la
vista:

* **Tres falsos positivos en la seccion 1.** Las vistas de la API de
  certificacion externa estan autenticadas, pero lo hacen en un decorador y el
  comando solo reconocia las vistas de funcion por unas cuantas palabras en su
  texto. Un aviso que siempre sale por algo que esta bien tapa los que no
  deberian salir.
* **Avisos que solo valen en local, impresos en produccion.** `bandit` no va a
  estar nunca en el servidor y `safety` tampoco; contarlos como «sin mirar» en
  cada despliegue es lo que acaba haciendo que nadie lea esa lista.

Las pruebas de los dos modos sustituyen a los tres escaneres de fuera: lo que
se comprueba es el comando --que los llame o no, como numere, que imprima--, no
bandit ni pip-audit, que ademas tardan y salen a la red.

    manage.py test apps.common.utils.tests.test_check_security \\
        --settings=app_core.settings_test
"""

import re
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.project.specific.documents.certificates import external

from ..management.commands import check_security
from ..management.commands.check_security import (INTENTIONALLY_PUBLIC,
                                                  INTENTIONALLY_PUBLIC_PATHS,
                                                  Command)
from ..scanners import ScanResult

EXTERNAL_VIEWS = ('external_issue', 'external_public_copy', 'external_revoke')

MODULE = 'apps.common.utils.management.commands.check_security'


# ----------------------------------------------------------------------
# Vistas de prueba. Estan en un modulo `apps.*`, que es lo unico que el comando
# audita, y se enrutan con su propio URLconf.

def unguarded(request):
    return None


@csrf_exempt
@require_POST
def unguarded_with_decorators(request):
    return None


@csrf_exempt
@require_POST
@external.issuer_required('issue')
def guarded_by_the_decorator(request):
    return None


@require_GET
@external.issuer_required('access')
def guarded_get(request):
    return None


def guarded_by_hand(request):
    if not request.user.is_staff:
        return None
    return None


urlpatterns = [
    path('probe/unguarded/', unguarded, name='probe_unguarded'),
    path('probe/decorated/', unguarded_with_decorators,
         name='probe_decorated'),
    path('probe/issuer/', guarded_by_the_decorator, name='probe_issuer'),
    path('probe/issuer-get/', guarded_get, name='probe_issuer_get'),
    path('probe/by-hand/', guarded_by_hand, name='probe_by_hand'),
]


def run_section_one() -> str:
    out = StringIO()
    command = Command(stdout=out)
    command.findings = []
    command.section_number = 0
    command.in_development = False
    command._check_unguarded_views()
    return out.getvalue()


# ----------------------------------------------------------------------
class ExternalViewsAreNotFalsePositivesTests(TestCase):

    def test_the_decorator_is_a_function_guard_token(self):
        self.assertIn('issuer_required', check_security.FUNCTION_GUARD_TOKENS)

    def test_inspect_sees_the_decorator_line_through_csrf_and_require_post(self):
        """
        Lo que se comprobo en vez de suponer: `getsource` de una vista
        envuelta por `csrf_exempt` y `require_POST` baja hasta la original y
        trae sus lineas de decorador.
        """
        import inspect

        for view in (external.issue_document, external.public_copy,
                     external.revoke_document):
            with self.subTest(view=view.__name__):
                source = inspect.getsource(inspect.unwrap(view))

                self.assertIn('@issuer_required(', source)
                self.assertTrue(Command()._function_has_guard(view))

    def test_the_three_views_do_not_come_out_as_unguarded(self):
        report = run_section_one()

        for name in EXTERNAL_VIEWS:
            with self.subTest(name=name):
                self.assertNotIn(name, report)
                self.assertNotIn('/api/certificates/external/', report)

        self.assertNotIn('AVISO', report)

    def test_they_are_not_hidden_in_the_list_of_public_views(self):
        """No son publicas: estan autenticadas. La lista no es para esto."""
        for name in EXTERNAL_VIEWS:
            with self.subTest(name=name):
                self.assertNotIn(f'certificates:{name}', INTENTIONALLY_PUBLIC)

        for route in INTENTIONALLY_PUBLIC_PATHS:
            self.assertNotIn('external', route)

    def test_the_decorator_is_what_makes_them_pass(self):
        """Sin el decorador, la misma vista sale: la deteccion no es ciega."""
        def bare(request):
            return None

        bare.__name__ = 'public_copy'

        self.assertFalse(Command()._function_has_guard(bare))


@override_settings(ROOT_URLCONF=__name__)
class AnUnguardedFunctionViewStillShowsUpTests(SimpleTestCase):

    def flagged(self):
        report = run_section_one()
        return {
            name for name in (
                'probe_unguarded', 'probe_decorated', 'probe_issuer',
                'probe_issuer_get', 'probe_by_hand',
            ) if f'tests:{name}' in report
        }

    def test_a_new_view_without_a_guard_is_flagged(self):
        self.assertIn('probe_unguarded', self.flagged())

    def test_decorators_that_are_not_a_guard_do_not_hide_it(self):
        """`csrf_exempt` y `require_POST` no son control de acceso."""
        self.assertIn('probe_decorated', self.flagged())

    def test_the_guarded_ones_are_not_flagged(self):
        flagged = self.flagged()

        self.assertNotIn('probe_issuer', flagged)
        self.assertNotIn('probe_issuer_get', flagged)
        self.assertNotIn('probe_by_hand', flagged)

    def test_only_the_unguarded_ones_are_flagged(self):
        self.assertEqual(
            self.flagged(), {'probe_unguarded', 'probe_decorated'})


# ----------------------------------------------------------------------
def scans(**results):
    """Los tres escaneres sustituidos; devuelve el parche y los mocks."""
    defaults = {
        'bandit': ScanResult(ran=True),
        'pip_audit': ScanResult(ran=True),
        'safety': ScanResult(ran=True),
    }
    defaults.update(results)

    patches = {
        'bandit': mock.patch(f'{MODULE}.run_bandit',
                             return_value=defaults['bandit']),
        'pip_audit': mock.patch(f'{MODULE}.run_pip_audit',
                                return_value=defaults['pip_audit']),
        'safety': mock.patch(f'{MODULE}.run_safety',
                             return_value=defaults['safety']),
    }

    return patches


def run_command(debug, **results):
    patches = scans(**results)
    mocks = {name: patch.start() for name, patch in patches.items()}

    try:
        out = StringIO()
        with override_settings(DEBUG=debug):
            call_command('check_security', stdout=out)
    finally:
        mock.patch.stopall()

    return out.getvalue(), mocks


def headings(report):
    return re.findall(r'^(\d+)\. (.+)$', report, re.M)


BANDIT_MISSING = ScanResult(
    skipped='bandit no esta instalado, asi que el codigo no se ha analizado.')
PIP_AUDIT_MISSING = ScanResult(
    skipped='pip-audit no esta instalado, asi que las dependencias no se han '
            'contrastado.')
SAFETY_BY_DESIGN = ScanResult(
    by_design=True, skipped='safety no esta instalado (previsto).')


class InProductionOnlyWhatMakesSenseTests(TestCase):

    def setUp(self):
        self.report, self.mocks = run_command(
            False, bandit=BANDIT_MISSING, safety=SAFETY_BY_DESIGN)

    def test_bandit_and_safety_are_not_even_run(self):
        self.mocks['bandit'].assert_not_called()
        self.mocks['safety'].assert_not_called()

    def test_pip_audit_does_run(self):
        self.mocks['pip_audit'].assert_called_once()

    def test_neither_is_printed(self):
        lowered = self.report.lower()

        self.assertNotIn('bandit', lowered)
        self.assertNotIn('safety', lowered)
        self.assertNotIn('SIN MIRAR', self.report)

    def test_nothing_is_counted_as_not_done(self):
        self.assertNotIn('no se han hecho', self.report)

    def test_the_notes_that_only_matter_locally_are_gone(self):
        self.assertNotIn('para que valga', self.report)
        self.assertNotIn('INSTALADO', self.report)
        self.assertNotIn('lanzalo', self.report)

    def test_the_sections_are_numbered_in_order_without_a_gap(self):
        numbers = [int(n) for n, _ in headings(self.report)]

        self.assertEqual(numbers, list(range(1, 8)))
        self.assertIn(
            ('7', 'Vulnerabilidades en las dependencias (pip-audit)'),
            headings(self.report))

    def test_pip_audit_missing_still_counts_as_a_gap(self):
        """En el servidor SI corre: que falte no es lo previsto."""
        report, _ = run_command(False, pip_audit=PIP_AUDIT_MISSING)

        self.assertIn('SIN MIRAR pip-audit', report)
        self.assertIn('1 comprobacion(es) no se han hecho', report)

    def test_a_real_finding_is_still_reported(self):
        report, _ = run_command(
            False, pip_audit=ScanResult(
                ran=True, findings=['pypdf 1.0 — 1 aviso(s)']))

        self.assertIn('AVISO pypdf 1.0', report)


class InDevelopmentNothingChangesTests(TestCase):

    def setUp(self):
        self.report, self.mocks = run_command(
            True, bandit=BANDIT_MISSING, safety=SAFETY_BY_DESIGN)

    def test_the_three_scanners_run(self):
        for name in ('bandit', 'pip_audit', 'safety'):
            with self.subTest(name=name):
                self.mocks[name].assert_called_once()

    def test_the_nine_sections_are_there_in_order(self):
        self.assertEqual(
            [(int(n)) for n, _ in headings(self.report)], list(range(1, 10)))
        self.assertIn(
            ('7', 'Analisis estatico del codigo (bandit)'),
            headings(self.report))
        self.assertIn(
            ('8', 'Vulnerabilidades en las dependencias (pip-audit)'),
            headings(self.report))
        self.assertIn(
            ('9', 'Segunda opinion sobre las dependencias (safety)'),
            headings(self.report))

    def test_a_missing_bandit_is_an_unmistakable_gap(self):
        self.assertIn('SIN MIRAR bandit no esta instalado', self.report)
        self.assertIn('1 comprobacion(es) no se han hecho', self.report)

    def test_safety_skipped_by_design_is_not_a_gap(self):
        self.assertIn('(omitida: safety no esta instalado', self.report)
        self.assertNotIn('SIN MIRAR safety', self.report)

    def test_the_notes_are_still_there(self):
        self.assertIn('para que valga, lanzalo con los ajustes de produccion',
                      self.report)
        self.assertIn('INSTALADO', self.report)

    def test_the_debug_setting_is_reported(self):
        self.assertIn('DEBUG esta activado', self.report)


class TheTwoModesAgreeOnTheSharedSectionsTests(TestCase):

    def test_sections_one_to_six_are_the_same_in_both(self):
        prod, _ = run_command(False)
        dev, _ = run_command(True)

        def titles(report):
            return [t for n, t in headings(report) if int(n) <= 6]

        self.assertEqual(titles(prod), titles(dev))
