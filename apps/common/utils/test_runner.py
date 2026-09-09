# apps/common/utils/test_runner.py
"""
Un runner que además de ejecutar las pruebas **cuenta lo que pasó**.

Django imprime el resultado y lo tira: quedan unos puntos, un número y un
«OK». Para un resumen con gráficas hace falta lo otro --qué prueba, de qué
app, cuánto tardó, cómo acabó-- y hay dos formas de obtenerlo.

La mala es parsear la salida de texto. Con ``--verbosity 2`` unittest imprime
el nombre y el resultado, pero el formato cambia entre versiones de Python
(en 3.11 la línea del identificador cambió), la primera línea del docstring se
cuela en medio, y un fallo mete un bloque de traza que hay que saltarse. Un
resumen construido así se rompe en una actualización de Python y nadie se
entera hasta que las gráficas mienten.

La buena es engancharse donde unittest ya lleva la cuenta: ``TestResult``. Sus
métodos ``addSuccess``, ``addFailure``, ``addError``, ``addSkip``… se llaman
con el objeto de prueba en la mano. Ahí no hay nada que interpretar.

El informe sale a un fichero JSON, no por pantalla: la salida estándar la usa
el propio corredor para su resumen de siempre, y mezclar las dos haría que
cualquiera de las dos estorbara a la otra.
"""

import json
import os
import time
import unittest
from pathlib import Path

from django.test.runner import DiscoverRunner

#: Dónde dejar el informe. Lo pone quien lanza el corredor, porque es quien
#: sabe dónde quiere leerlo después.
REPORT_ENV = 'GEA_TEST_REPORT'

#: Los desenlaces posibles. Son cinco y no dos: un `skip` no es un fallo pero
#: tampoco es una prueba que haya comprobado algo, y contarlo como éxito
#: infla el resumen justo donde conviene no engañarse.
PASSED = 'passed'
FAILED = 'failed'
ERRORED = 'errored'
SKIPPED = 'skipped'
EXPECTED = 'expected_failure'


def app_of(test) -> str:
    """
    A qué app pertenece una prueba, leída de su módulo.

    ``apps.common.utils.tests.test_backup`` → ``common.utils``. Se corta por
    ``tests`` porque el paquete de pruebas cuelga de la app, así que lo que
    hay antes es la app y lo que hay después es el fichero.
    """
    module = getattr(test, '__module__', '') or ''
    parts = module.split('.')

    if 'tests' in parts:
        parts = parts[:parts.index('tests')]

    if parts and parts[0] == 'apps':
        parts = parts[1:]

    return '.'.join(parts) or 'sin app'


class RecordingResult(unittest.TextTestResult):
    """
    El resultado de siempre, tomando nota por el camino.

    Hereda de ``TextTestResult`` y no lo sustituye: la salida por pantalla
    tiene que seguir siendo exactamente la misma. Lo único que se añade es una
    lista.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []
        self._started_at = None

    # -- el reloj -------------------------------------------------------
    def startTest(self, test):
        self._started_at = time.perf_counter()
        super().startTest(test)

    def _elapsed(self) -> float:
        if self._started_at is None:
            return 0.0

        return round(time.perf_counter() - self._started_at, 4)

    def _note(self, test, outcome, detail=''):
        self.records.append({
            'id': test.id(),
            'app': app_of(test),
            'module': getattr(test, '__module__', ''),
            'outcome': outcome,
            # Segundos. Se guarda por prueba y no sólo el total porque el dato
            # que sirve para algo es cuál es la lenta, no cuánto tarda la suite.
            'seconds': self._elapsed(),
            # Recortado: una traza entera por prueba convierte el informe en
            # un fichero de megabytes, y para el resumen basta la primera
            # línea. La traza completa sigue estando en la salida del corredor.
            'detail': (detail or '').strip().splitlines()[-1][:300]
            if detail else '',
        })

    # -- los desenlaces -------------------------------------------------
    def addSuccess(self, test):
        super().addSuccess(test)
        self._note(test, PASSED)

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._note(test, FAILED, self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self._note(test, ERRORED, self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._note(test, SKIPPED, reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._note(test, EXPECTED)

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        # Una prueba marcada como «se espera que falle» que pasa es un fallo:
        # o el error se arregló y sobra la marca, o la prueba dejó de mirar lo
        # que miraba.
        self._note(test, FAILED, 'pasó una prueba marcada como fallo esperado')


class JSONReportRunner(DiscoverRunner):
    """
    El corredor de Django, escribiendo además un informe en JSON.

    Se usa así, y no se instala como corredor por defecto:

        manage.py test --testrunner=apps.common.utils.test_runner.JSONReportRunner

    Que no sea el de por defecto es deliberado: quien ejecuta las pruebas a
    mano quiere la salida de siempre y ningún fichero suelto. El informe lo
    pide ``manage.py test_report``, que es quien lo va a leer.
    """

    def get_resultclass(self):
        # `--debug-sql` y `--pdb` sustituyen la clase de resultado por las
        # suyas. Si alguien las pide, ganan ellas y no hay informe: es mejor
        # eso que un informe a medias sin avisar.
        return super().get_resultclass() or RecordingResult

    def run_suite(self, suite, **kwargs):
        started = time.time()
        result = super().run_suite(suite, **kwargs)

        self._write_report(result, started)

        return result

    def _write_report(self, result, started):
        target = os.environ.get(REPORT_ENV)

        if not target or not hasattr(result, 'records'):
            return

        records = result.records

        payload = {
            'generated_at': started,
            'finished_at': time.time(),
            'duration': round(time.time() - started, 2),
            'totals': {
                name: sum(1 for r in records if r['outcome'] == name)
                for name in (PASSED, FAILED, ERRORED, SKIPPED, EXPECTED)
            },
            'total': len(records),
            'tests': records,
        }

        try:
            path = Path(target)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding='utf-8',
            )
        except OSError:
            # Que no se pueda escribir el informe no puede cambiar el
            # resultado de las pruebas, que es lo que de verdad importa.
            pass
