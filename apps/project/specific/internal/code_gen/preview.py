# apps/project/specific/internal/code_gen/preview.py
"""
Contenedor HTML de la vista previa de estampado.

El marcado es un hueco vacio con los datos de configuracion: toda la geometria
la calcula ``static/js/stamp_preview.js``, que replica
``services/pdf_stamp.py::_resolve_position``. Se comparte entre el admin y el
dashboard para que ambos usen exactamente el mismo componente.
"""

import json
import logging

from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .constants import DEFAULT_PAGE_HEIGHT_PT, DEFAULT_PAGE_WIDTH_PT

logger = logging.getLogger(__name__)


def preview_labels() -> dict:
    """Textos traducibles que el componente pinta en cliente."""
    return {
        'page': _('Page size'),
        'hint': _('Drag a box to move it; the offsets update as you go.'),
        'loading': _('Rendering the document…'),
        'pdffailed': _(
            'The document could not be rendered; the placements still work.'
        ),
        'empty': _('No placements yet. Add one to see it here.'),
        'outside': _('This placement falls outside the page.'),
        'resize': _(
            'Drag a corner to resize keeping the proportion, or an edge to '
            'change only the width or the height.'
        ),
        'fitted': _(
            'The symbol keeps its proportion, so it uses %(w)s x %(h)s pt of '
            'the %(bw)s x %(bh)s pt box.'
        ),
        'exact': _('The symbol fills the box exactly.'),
        'samplelength': _('Sample characters'),
        'samplehint': _(
            'Number of characters in the sample barcode. The more characters, '
            'the wider the symbol gets.'
        ),
    }


def render_preview_container(
    *,
    row_selector: str = '',
    form_scope: str = '',
    pdf_input: str = '',
    placements=None,
    editable: bool = False,
    extra_class: str = '',
    page_width: float = DEFAULT_PAGE_WIDTH_PT,
    page_height: float = DEFAULT_PAGE_HEIGHT_PT,
    barcode_payload: str = '',
):
    """
    Devuelve el ``<div>`` que el JS convierte en vista previa.

    Parameters:
        row_selector (str): selector CSS de las filas del formset, cuando la
            vista previa se alimenta de un formulario.
        form_scope (str): selector del contenedor donde escuchar los cambios.
        placements (list | None): posiciones fijas, para el modo solo lectura.
        editable (bool): permite arrastrar y redimensionar las cajas.
        extra_class (str): clases adicionales del contenedor.
        barcode_payload (str): codigo real a dibujar en la muestra. Vacio
            dibuja una carga de ejemplo de la longitud recomendada.

    Returns:
        SafeString: el contenedor listo para insertar en una plantilla.
    """
    labels = preview_labels()

    # Los simbolos van embebidos de salida para que la vista previa sea fiel
    # sin esperar a ninguna peticion; el endpoint solo hace falta cuando el
    # operador cambia la longitud de la muestra.
    from .services.samples import (BARCODE_SAMPLE_DEFAULT_LENGTH,
                                   BARCODE_SAMPLE_MAX_LENGTH,
                                   BARCODE_SAMPLE_MIN_LENGTH, sample_symbols)

    try:
        symbols = sample_symbols(barcode_payload=barcode_payload)
    except Exception:                      # pragma: no cover - defensivo
        # Una muestra que no se pueda dibujar no puede tumbar la pagina: sin
        # simbolos la vista previa vuelve a las cajas de color de siempre.
        logger.warning('Sample symbols unavailable', exc_info=True)
        symbols = {}

    return format_html(
        '<div data-gea-preview="1" class="{}" '
        'data-page-width="{}" data-page-height="{}" '
        'data-row-selector="{}" data-form-scope="{}" '
        'data-pdf-input="{}" '
        'data-editable="{}" data-placements="{}" '
        'data-label-page="{}" data-label-hint="{}" '
        'data-label-empty="{}" data-label-outside="{}" '
        'data-label-loading="{}" data-label-pdffailed="{}" '
        'data-label-resize="{}" data-label-fitted="{}" '
        'data-label-exact="{}" data-label-samplelength="{}" '
        'data-label-samplehint="{}" '
        'data-symbols="{}" data-symbols-url="{}" '
        'data-sample-length="{}" data-sample-min="{}" '
        'data-sample-max="{}"></div>',
        extra_class,
        page_width,
        page_height,
        row_selector,
        form_scope,
        pdf_input,
        'true' if editable else 'false',
        json.dumps(placements) if placements is not None else '',
        labels['page'],
        labels['hint'],
        labels['empty'],
        labels['outside'],
        labels['loading'],
        labels['pdffailed'],
        labels['resize'],
        labels['fitted'],
        labels['exact'],
        labels['samplelength'],
        labels['samplehint'],
        json.dumps(symbols),
        reverse('code_gen:preview_symbols'),
        BARCODE_SAMPLE_DEFAULT_LENGTH,
        BARCODE_SAMPLE_MIN_LENGTH,
        BARCODE_SAMPLE_MAX_LENGTH,
    )


def placements_as_data(layout) -> list:
    """Serializa las posiciones de un layout para el modo solo lectura."""
    if layout is None:
        return []

    return layout.placement_data()
