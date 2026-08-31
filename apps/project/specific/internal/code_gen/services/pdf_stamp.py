# apps/project/specific/internal/code_gen/services/pdf_stamp.py
"""
Incrustacion de los simbolos dentro del PDF.

Se genera una capa (overlay) con ReportLab por cada pagina afectada y se
fusiona sobre la pagina original con pypdf. El PDF de origen no se
reconstruye: se conserva su contenido tal cual y solo se le anade el
contenido de la capa.

Sistema de coordenadas: puntos PostScript (72 pt = 1 pulgada), medidos desde
la esquina indicada en ``anchor`` hacia el interior de la pagina. Para los
anclajes centrados, ``offset_x`` es un desplazamiento respecto del centro.
"""

import logging
from dataclasses import dataclass, field
from io import BytesIO
from typing import Dict, Iterable, List, Sequence

from pypdf import PdfReader, PdfWriter, Transformation
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdf_canvas

logger = logging.getLogger(__name__)

ANCHOR_BOTTOM_LEFT = 'BL'
ANCHOR_BOTTOM_CENTER = 'BC'
ANCHOR_BOTTOM_RIGHT = 'BR'
ANCHOR_TOP_LEFT = 'TL'
ANCHOR_TOP_CENTER = 'TC'
ANCHOR_TOP_RIGHT = 'TR'


@dataclass
class StampSpec:
    """Un simbolo a incrustar y donde va."""

    image_png: bytes
    pages: Sequence[int]
    anchor: str = ANCHOR_BOTTOM_RIGHT
    offset_x: float = 28.0
    offset_y: float = 28.0
    width: float = 84.0
    height: float = 84.0
    opacity: float = 1.0
    label: str = ''


@dataclass
class StampReport:
    """Resultado del estampado, util para avisar al operador."""

    page_count: int = 0
    applied: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)


def _resolve_position(
    anchor: str,
    page_width: float,
    page_height: float,
    spec: StampSpec
) -> tuple:
    """Convierte anclaje + offsets en la esquina inferior izquierda del simbolo."""
    if anchor in (ANCHOR_BOTTOM_RIGHT, ANCHOR_TOP_RIGHT):
        x = page_width - spec.offset_x - spec.width
    elif anchor in (ANCHOR_BOTTOM_CENTER, ANCHOR_TOP_CENTER):
        x = ((page_width - spec.width) / 2.0) + spec.offset_x
    else:
        x = spec.offset_x

    if anchor in (ANCHOR_TOP_LEFT, ANCHOR_TOP_CENTER, ANCHOR_TOP_RIGHT):
        y = page_height - spec.offset_y - spec.height
    else:
        y = spec.offset_y

    return x, y


def stamp_pdf(source: bytes, stamps: Iterable[StampSpec]) -> tuple:
    """
    Incrusta los simbolos en el PDF.

    Parameters:
        source (bytes): PDF original.
        stamps (Iterable[StampSpec]): simbolos y posiciones.

    Returns:
        tuple[bytes, StampReport]: PDF resultante y detalle de lo aplicado.
    """
    stamps = list(stamps)

    writer = PdfWriter(clone_from=BytesIO(source))
    page_count = len(writer.pages)
    report = StampReport(page_count=page_count)

    by_page: Dict[int, List[StampSpec]] = {}
    for spec in stamps:
        valid_pages = [
            index for index in spec.pages
            if 0 <= index < page_count
        ]

        if not valid_pages:
            report.skipped.append(
                spec.label or f'{spec.anchor} stamp (no matching page)'
            )
            continue

        for index in valid_pages:
            by_page.setdefault(index, []).append(spec)

    for index, page_stamps in sorted(by_page.items()):
        page = writer.pages[index]

        if page.get('/Rotate'):
            try:
                page.transfer_rotation_to_content()
            except Exception:
                logger.exception(
                    'Could not normalise the rotation of page %s', index
                )

        box = page.mediabox
        left = float(box.left)
        bottom = float(box.bottom)
        width = float(box.right) - left
        height = float(box.top) - bottom

        buffer = BytesIO()
        overlay = pdf_canvas.Canvas(buffer, pagesize=(width, height))

        for spec in page_stamps:
            x, y = _resolve_position(spec.anchor, width, height, spec)

            overlay.saveState()

            if spec.opacity is not None and spec.opacity < 1.0:
                overlay.setFillAlpha(float(spec.opacity))
                overlay.setStrokeAlpha(float(spec.opacity))

            overlay.drawImage(
                ImageReader(BytesIO(spec.image_png)),
                x,
                y,
                width=spec.width,
                height=spec.height,
                mask='auto',
                preserveAspectRatio=True,
                # Centrado, no pegado al vertice inferior izquierdo. Un
                # simbolo casi nunca tiene la proporcion exacta de la caja que
                # se le asigna --un Code128 es mas ancho cuanto mas largo es el
                # codigo--, asi que con 'sw' quedaba descolgado hacia un lado y
                # el hueco sobrante caia todo al otro. La vista previa hace lo
                # mismo: si cambia uno, cambia el otro.
                anchor='c',
            )

            overlay.restoreState()

            report.applied.append(
                spec.label or f'{spec.anchor} stamp on page {index + 1}'
            )

        overlay.showPage()
        overlay.save()
        buffer.seek(0)

        overlay_page = PdfReader(buffer).pages[0]

        page.merge_transformed_page(
            overlay_page,
            Transformation().translate(left, bottom),
            over=True,
        )

    output = BytesIO()
    writer.write(output)
    writer.close()

    return output.getvalue(), report


def pdf_page_count(source: bytes) -> int:
    """Numero de paginas de un PDF, o 0 si no se puede leer."""
    try:
        return len(PdfReader(BytesIO(source)).pages)
    except Exception:
        return 0
