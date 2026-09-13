# apps/common/utils/tests/test_scanners.py
"""
Que los dos escaneres de fuera digan la verdad, y que ninguno se cuelgue.

Tres familias de trampa, y las tres han costado algo en algun sitio:

* **Un escaner que no se ejecuto no es un escaner en verde.** Si `bandit` no
  esta instalado, la seccion tiene que decirlo; contarlo como "sin hallazgos"
  convierte un informe de seguridad en una media verdad.
* **Un escaner que pregunta se cuelga.** Safety CLI 3 siempre se autentica, y
  sin credencial se queda esperando en el terminal. Esto corre por cron y
  desde la consola de operaciones, donde no hay nadie que conteste.
* **Una clave en la linea de comandos deja de ser una clave.** La ve cualquiera
  que liste procesos, y ademas la consola guarda la linea ejecutada y su salida
  en `CommandRunModel`.

    manage.py test apps.common.utils.tests.test_scanners \\
        --settings=app_core.settings_test
"""

import json
import os
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase

from .. import scanners
from ..scanners import (BANDIT_ACCEPTED, SAFETY_KEY_ENV, _first_json_object,
                        _safety_findings, run_bandit, run_safety)


class TheAcceptedListIsHonestTests(SimpleTestCase):
    """
    Cada excepcion lleva su motivo escrito, como `NEVER_EXPOSED` o
    `CANNOT_BE_PINNED`. Una lista de exclusion sin motivos es una forma comoda
    de no mirar.
    """

    def test_every_entry_says_why(self):
        """
        O lo explica, o remite a la entrada que lo explica.

        La remision es un motivo valido y es corta por naturaleza --"Ver B308
        del mismo fichero"--; que resuelva de verdad lo comprueba
        `test_a_cross_reference_points_at_a_real_entry`. Lo que no vale es una
        entrada con media frase suelta.
        """
        for key, reason in BANDIT_ACCEPTED.items():
            text = str(reason)

            if text.startswith('Ver '):
                continue

            self.assertGreater(
                len(text), 30,
                f'{key} esta aceptado sin explicar por que',
            )

    def test_every_entry_points_at_a_file_that_exists(self):
        """
        Una entrada que apunta a un fichero movido o borrado no protege nada y
        **si** puede silenciar: deja de casar, pero nadie se entera de que
        sobra. Peor aun si el fichero vuelve con otro contenido.
        """
        base = Path(settings.BASE_DIR)
        missing = [
            path for _rule, path in BANDIT_ACCEPTED
            if not (base / path).exists()
        ]

        self.assertEqual(
            missing, [],
            'estas rutas ya no existen; quita su entrada de BANDIT_ACCEPTED',
        )

    def test_a_cross_reference_points_at_a_real_entry(self):
        """
        Varias entradas dicen "Ver B404 del mismo fichero". Si la referida no
        existe, la razon escrita no lleva a ninguna parte.
        """
        for (rule, path), reason in BANDIT_ACCEPTED.items():
            text = str(reason)

            if not text.startswith('Ver '):
                continue

            referred = text.split()[1]

            self.assertIn(
                (referred, path), BANDIT_ACCEPTED,
                f'{rule} en {path} remite a {referred}, que no esta',
            )


class WhatHappensWithoutTheToolTests(SimpleTestCase):

    def test_bandit_missing_is_not_a_clean_run(self):
        with mock.patch.object(scanners, '_module_available',
                               return_value=False):
            result = run_bandit()

        self.assertFalse(result.ran)
        self.assertEqual(result.findings, [])
        self.assertIn('bandit', result.skipped)
        # Y dice como conseguirla, que es la mitad util del aviso.
        self.assertIn('uv add', result.skipped)

    def test_safety_missing_is_not_a_clean_run(self):
        with mock.patch.object(scanners, '_module_available',
                               return_value=False):
            result = run_safety()

        self.assertFalse(result.ran)
        self.assertEqual(result.findings, [])
        self.assertIn('safety', result.skipped)


class SafetyNeverWaitsForAnAnswerTests(SimpleTestCase):
    """
    Lo que haria que un cron se quedara colgado para siempre.
    """

    def setUp(self):
        self.previous = os.environ.get(SAFETY_KEY_ENV)
        self.addCleanup(self._restore)

    def _restore(self):
        if self.previous is None:
            os.environ.pop(SAFETY_KEY_ENV, None)
        else:
            os.environ[SAFETY_KEY_ENV] = self.previous

    def test_without_a_key_it_is_not_even_launched(self):
        os.environ.pop(SAFETY_KEY_ENV, None)

        with mock.patch.object(scanners, '_module_available',
                               return_value=True), \
                mock.patch.object(scanners.subprocess, 'run') as launched:
            result = run_safety()

        launched.assert_not_called()
        self.assertFalse(result.ran)
        self.assertIn(SAFETY_KEY_ENV, result.skipped)

    def test_the_key_travels_in_the_environment_and_never_in_the_argv(self):
        """
        El detalle que convierte una clave en un secreto publicado: `--key=...`
        lo ve cualquiera que liste procesos, y aqui ademas quedaria escrito en
        CommandRunModel junto con la salida.
        """
        os.environ[SAFETY_KEY_ENV] = 'una-clave-de-prueba'

        with mock.patch.object(scanners, '_module_available',
                               return_value=True), \
                mock.patch.object(scanners.subprocess, 'run') as launched:
            launched.return_value = mock.Mock(
                stdout='{"scan_results": {"files": []}}', stderr='',
                returncode=0)
            run_safety()

        argv, kwargs = launched.call_args[0][0], launched.call_args[1]

        self.assertNotIn('--key', argv)

        for piece in argv:
            self.assertNotIn('una-clave-de-prueba', str(piece))

        self.assertEqual(
            kwargs['env'][SAFETY_KEY_ENV], 'una-clave-de-prueba')

    def test_it_is_launched_with_the_input_closed(self):
        """
        Con la entrada cerrada y en modo cicd no puede pedir nada, ni aunque
        una version futura vuelva a intentarlo.
        """
        import subprocess

        os.environ[SAFETY_KEY_ENV] = 'una-clave-de-prueba'

        with mock.patch.object(scanners, '_module_available',
                               return_value=True), \
                mock.patch.object(scanners.subprocess, 'run') as launched:
            launched.return_value = mock.Mock(
                stdout='{"scan_results": {"files": []}}', stderr='',
                returncode=0)
            run_safety()

        argv = launched.call_args[0][0]
        kwargs = launched.call_args[1]

        self.assertIn('--stage', argv)
        self.assertIn('cicd', argv)
        self.assertIs(kwargs['stdin'], subprocess.DEVNULL)


SAFETY_PAYLOAD = {
    'scan_results': {
        'files': [{
            'location': 'requirements.txt',
            'results': {
                'dependencies': [{
                    'name': 'ejemplo',
                    'specifications': [{
                        'raw': 'ejemplo==1.0.0',
                        'vulnerabilities': {
                            'known_vulnerabilities': [
                                {'id': 'CVE-2026-0001', 'severity': 'high'},
                                {'id': 'PYSEC-2026-2', 'severity': None},
                            ],
                        },
                    }],
                }],
            },
        }],
    },
}


class ReadingSafetysAnswerTests(SimpleTestCase):

    def test_every_vulnerability_becomes_a_line(self):
        findings = _safety_findings(SAFETY_PAYLOAD)

        self.assertEqual(len(findings), 2)
        self.assertIn('CVE-2026-0001', findings[0])
        self.assertIn('ejemplo==1.0.0', findings[0])

    def test_a_vulnerability_without_severity_still_shows_up(self):
        """
        Perder un hallazgo por un campo vacio seria el peor fallo posible
        aqui: silencioso y en la direccion insegura.
        """
        findings = _safety_findings(SAFETY_PAYLOAD)

        self.assertIn('PYSEC-2026-2', findings[1])
        self.assertIn('sin severidad', findings[1])

    def test_an_empty_report_is_no_findings(self):
        self.assertEqual(
            _safety_findings({'scan_results': {'files': []}}), [])

    def test_a_shape_it_does_not_know_does_not_crash(self):
        """
        El formato de safety ha cambiado entre versiones mayores. Que no lo
        reconozca tiene que dar cero hallazgos, no una excepcion que se lleve
        por delante el resto del informe de seguridad.
        """
        self.assertEqual(_safety_findings({}), [])
        self.assertEqual(_safety_findings({'scan_results': None}), [])

    def test_the_json_is_found_after_the_noise_it_prints_first(self):
        """
        Safety escribe avisos de deprecacion de sus propias dependencias antes
        del informe. Leer desde la primera llave evita que un aviso nuevo en
        una version futura rompa la lectura.
        """
        noisy = (
            'AuthlibDeprecationWarning: authlib.jose esta deprecado\n'
            '  from authlib.jose.errors import ExpiredTokenError\n'
            + json.dumps(SAFETY_PAYLOAD)
        )

        self.assertEqual(_first_json_object(noisy), SAFETY_PAYLOAD)

    def test_output_without_any_json_is_read_as_no_object(self):
        self.assertIsNone(_first_json_object('safety exploto'))
        self.assertIsNone(_first_json_object(''))


class BanditOverThisProjectTests(SimpleTestCase):
    """
    La prueba de verdad: pasar bandit sobre este repositorio.

    Se salta sola si bandit no esta instalado, porque es opcional a proposito
    y no se va a convertir en obligatoria por la puerta de atras de una
    prueba que falla.
    """

    def test_nothing_new_is_flagged(self):
        result = run_bandit()

        if not result.ran:
            self.skipTest(result.skipped or result.error)

        self.assertEqual(
            result.findings, [],
            'bandit ve algo que no esta razonado; arreglalo o metelo en '
            'BANDIT_ACCEPTED con su motivo',
        )

    def test_the_accepted_ones_are_actually_being_used(self):
        """
        Si el numero de aceptados cae a cero es que la exclusion de pruebas y
        migraciones se comio el analisis entero, o que bandit cambio de
        formato. Un escaner que no mira nada tambien sale en verde.
        """
        result = run_bandit()

        if not result.ran:
            self.skipTest(result.skipped or result.error)

        self.assertGreater(result.accepted, 0)
