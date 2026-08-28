# apps/project/specific/internal/code_gen/preview.py
"""
Contenedor HTML de la vista previa de estampado.

El marcado es un hueco vacio con los datos de configuracion: toda la geometria
la calcula ``static/js/stamp_preview.js``, que replica
``services/pdf_stamp.py::_resolve_position``. Se comparte entre el admin y el
dashboard para que ambos usen exactamente el mismo componente.
"""

import json

from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .constants import DEFAULT_PAGE_HEIGHT_PT, DEFAULT_PAGE_WIDTH_PT


def preview_labels() -> dict:
    """Textos traducibles que el componente pinta en cliente."""
    return {
        'page': _('Page size'),
        'hint': _('Drag a box to move it; the offsets update as you go.'),
        'empty': _('No placements yet. Add one to see it here.'),
        'outside': _('This placement falls outside the page.'),
    }


def render_preview_container(
    *,
    row_selector: str = '',
    form_scope: str = '',
    placements=None,
    editable: bool = False,
    extra_class: str = '',
    page_width: float = DEFAULT_PAGE_WIDTH_PT,
    page_height: float = DEFAULT_PAGE_HEIGHT_PT,
):
    """
    Devuelve el ``<div>`` que el JS convierte en vista previa.

    Parameters:
        row_selector (str): selector CSS de las filas del formset, cuando la
            vista previa se alimenta de un formulario.
        form_scope (str): selector del contenedor donde escuchar los cambios.
        placements (list | None): posiciones fijas, para el modo solo lectura.
        editable (bool): permite arrastrar las cajas.
        extra_class (str): clases adicionales del contenedor.

    Returns:
        SafeString: el contenedor listo para insertar en una plantilla.
    """
    labels = preview_labels()

    return format_html(
        '<div data-gea-preview="1" class="{}" '
        'data-page-width="{}" data-page-height="{}" '
        'data-row-selector="{}" data-form-scope="{}" '
        'data-editable="{}" data-placements="{}" '
        'data-label-page="{}" data-label-hint="{}" '
        'data-label-empty="{}" data-label-outside="{}"></div>',
        extra_class,
        page_width,
        page_height,
        row_selector,
        form_scope,
        'true' if editable else 'false',
        json.dumps(placements) if placements is not None else '',
        labels['page'],
        labels['hint'],
        labels['empty'],
        labels['outside'],
    )


def placements_as_data(layout) -> list:
    """Serializa las posiciones de un layout para el modo solo lectura."""
    if layout is None:
        return []

    return layout.placement_data()
