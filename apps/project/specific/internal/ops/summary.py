# apps/project/specific/internal/ops/summary.py
"""
Lee el informe que deja ``manage.py test_report`` y lo deja listo para pintar.

Vive aparte de la vista por dos razones. La primera es que se pueda probar sin
levantar una petición: dar de comer un informe y mirar lo que sale es lo único
que hace falta para saber si el resumen dice la verdad. Y la segunda es que
**la plantilla no calcula nada**: recibe los porcentajes ya hechos. Una regla
de tres dentro de un ``{% widthratio %}`` es donde se cuelan las barras que no
suman cien y los redondeos que no cuadran con el número de al lado.

Lo que no hace este módulo: ejecutar pruebas. Eso es del comando, que corre en
subproceso. Aquí sólo se lee un JSON que ya está escrito.
"""

import json
from pathlib import Path

from django.conf import settings
from django.utils.translation import gettext_lazy as _

from apps.common.utils.management.commands.test_report import (LATEST,
                                                               REPORTS_DIR)
from apps.common.utils.test_runner import (ERRORED, EXPECTED, FAILED, PASSED,
                                           SKIPPED)

#: Cómo se llama y se pinta cada desenlace.
#:
#: El color va **siempre** con su icono y su etiqueta, y no es decoración: en
#: la paleta de estado el verde y el rojo se separan un ΔE de 4 bajo
#: deuteranopia, o sea que para bastante gente son el mismo color. Quien no
#: distinga los dos tiene que poder leer cuál es cuál.
OUTCOMES = (
    (PASSED, _('Pass'), '✓', 'good'),
    (FAILED, _('Fail'), '✕', 'critical'),
    (ERRORED, _('Error'), '▲', 'serious'),
    (SKIPPED, _('Skipped'), '–', 'warning'),
    (EXPECTED, _('Expected failure'), '~', 'muted'),
)

#: Cuántas de las lentas se pintan. Diez es lo que cabe de un vistazo y lo que
#: hace falta: la lista entera de 750 no es una gráfica, es la tabla.
SLOWEST = 10


def reports_dir() -> Path:
    return Path(settings.MEDIA_ROOT) / REPORTS_DIR


def latest_report():
    """El último informe escrito, o ``None`` si todavía no hay ninguno."""
    try:
        return json.loads(
            (reports_dir() / LATEST).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _percent(part, whole) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def _split(test_id: str):
    """
    Parte un identificador en «qué prueba» y «dónde vive».

    ``apps.common.utils.tests.test_backup.TheEnvelopeTests.test_it_opens``
    se lee mucho mejor como *test_it_opens* con
    *…tests.test_backup.TheEnvelopeTests* en gris al lado. Puesto entero, la
    parte que distingue una fila de la siguiente queda al final de una línea
    de cien caracteres.
    """
    parts = test_id.rsplit('.', 2)

    if len(parts) < 3:
        return test_id, ''

    where, case, name = parts

    return name, f'{where}.{case}'


def _outcomes(report):
    totals = report.get('totals', {})
    total = report.get('total', 0)

    rows = []

    for key, label, icon, tone in OUTCOMES:
        count = totals.get(key, 0)

        # Un desenlace que no ocurrió no ocupa sitio: cinco filas de las que
        # tres son cero es una leyenda, no un resumen.
        if not count:
            continue

        rows.append({
            'key': key,
            'label': label,
            'icon': icon,
            'tone': tone,
            'count': count,
            'percent': _percent(count, total),
        })

    return rows


def _apps(report):
    """Cuántas pruebas tiene cada app, y cuántas están en rojo."""
    buckets = {}

    for test in report.get('tests', []):
        bucket = buckets.setdefault(
            test['app'], {'app': test['app'], 'total': 0, 'red': 0,
                          'skipped': 0})
        bucket['total'] += 1

        if test['outcome'] in (FAILED, ERRORED):
            bucket['red'] += 1
        elif test['outcome'] == SKIPPED:
            bucket['skipped'] += 1

    rows = sorted(buckets.values(), key=lambda row: -row['total'])
    biggest = rows[0]['total'] if rows else 0

    for row in rows:
        # La barra se mide contra la app con más pruebas, no contra el total:
        # con 750 pruebas repartidas en trece apps, medir contra el total deja
        # todas las barras pegadas al eje y la gráfica no dice nada.
        row['width'] = _percent(row['total'], biggest)

    return rows


def _slowest(report):
    rows = sorted(
        report.get('tests', []),
        key=lambda test: test.get('seconds', 0.0),
        reverse=True,
    )[:SLOWEST]

    slowest = rows[0]['seconds'] if rows else 0.0

    return [{
        'id': row['id'],
        'name': _split(row['id'])[0],
        'where': _split(row['id'])[1],
        'seconds': row['seconds'],
        'width': _percent(row['seconds'], slowest),
    } for row in rows]


def _failures(report):
    rows = [test for test in report.get('tests', [])
            if test['outcome'] in (FAILED, ERRORED)]

    return [{
        'id': row['id'],
        'name': _split(row['id'])[0],
        'where': _split(row['id'])[1],
        'detail': row['detail'],
        'tone': 'critical' if row['outcome'] == FAILED else 'serious',
        'icon': '✕' if row['outcome'] == FAILED else '▲',
    } for row in rows]


def shape(report):
    """
    Todo lo que la plantilla necesita, ya calculado.

    Devuelve ``None`` si no hay informe: la página tiene un estado vacío que
    dice cómo generarlo, que es más útil que una gráfica de ceros.
    """
    if not report:
        return None

    total = report.get('total', 0)
    totals = report.get('totals', {})
    green = totals.get(PASSED, 0) + totals.get(EXPECTED, 0)

    coverage = report.get('coverage')

    return {
        'meta': report,
        'total': total,
        'totals': totals,
        # La cifra que encabeza la página. Los fallos esperados cuentan como
        # verde porque lo son: la prueba comprobó lo que decía comprobar.
        'pass_rate': _percent(green, total),
        'red': totals.get(FAILED, 0) + totals.get(ERRORED, 0),
        'outcomes': _outcomes(report),
        'apps': _apps(report),
        'slowest': _slowest(report),
        'failures': _failures(report),
        'coverage': coverage,
    }
