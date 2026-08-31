# apps/project/specific/internal/code_gen/services/summary.py
"""
Emision del documento resumen (AEGIS-6).

El resumen es el unico documento que lleva **codigos de otros**: sobre su PDF
se estampa el codigo de barras de cada miembro del resumen, ademas de su propio
par QR/barcode y del QR del anclaje.

Orden obligatorio, por la circularidad:

    1. ``seal_summary()``      master hash de los N miembros
    2. ``certify_summary()``   se emite el PDF llevando ese hash
    3. el propio resumen queda registrado como un documento mas, con su huella

El master hash no cubre al resumen. Nunca puede: no existe hasta que el hash
esta calculado.
"""

import logging
from typing import List, Optional

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from ..constants import (DEFAULT_BARCODE_HEIGHT_PT, DEFAULT_BARCODE_WIDTH_PT,
                         DEFAULT_MARGIN_PT, DEFAULT_QR_SIZE_PT,
                         HASH_B64_DEFAULT_LENGTH)
from .anchoring import anchor_url
from .certification import CertificationError, CodeOptions, certify_document
from .codes import validate_barcode_payload
from .hashing import hash_to_base64
from .pdf_stamp import StampSpec, pdf_page_count, stamp_pdf
from .render import render_barcode_png, render_qr_png

logger = logging.getLogger(__name__)

# Prefijo del master hash que va en el codigo de barras del resumen. Los 64
# caracteres completos harian un simbolo ilegible; 32 son 128 bits, de sobra
# para identificar, y el hash entero va en la pagina del anclaje.
MASTER_BARCODE_LENGTH = 32


def master_barcode_payload(summary) -> str:
    """
    Texto del codigo de barras propio del resumen.

    Hexadecimal, que pasa el filtro de Code128 sin problema (solo 0-9A-F).
    """
    if not summary.master_hash:
        raise CertificationError(
            str(_('Seal the summary before issuing its document.'))
        )

    return summary.master_hash[:MASTER_BARCODE_LENGTH].upper()


def build_summary_stamps(summary, layout, page_count: int) -> List[StampSpec]:
    """
    Traduce el layout del resumen a especificaciones de estampado.

    A diferencia de un certificado normal, aqui hay cuatro tipos de simbolo:
    los dos de siempre, el codigo de barras de cada miembro, y el QR del
    anclaje.
    """
    from ..models import CodeKindChoices

    members = {
        member.code: member
        for member in summary.ordered_members()
    }

    # Simbolos propios del resumen.
    own_barcode = render_barcode_png(master_barcode_payload(summary))
    own_qr = render_qr_png(
        summary_verification_payload(summary)
    )
    anchor_qr = render_qr_png(anchor_url(summary))

    # El codigo de barras de cada miembro se re-renderiza desde su payload
    # almacenado: nunca se copia la imagen, para que no pueda desincronizarse
    # del codigo realmente emitido.
    member_barcodes = {}
    for code, member in members.items():
        payload = member.document.code_payload
        if not payload:
            continue
        try:
            member_barcodes[code] = render_barcode_png(payload)
        except Exception:
            logger.exception(
                'Could not render the barcode of member %s', code
            )

    specs: List[StampSpec] = []

    placements = (
        layout.placements.filter(is_active=True)
        if layout is not None else []
    )

    for placement in placements:
        if placement.kind == CodeKindChoices.MEMBER_BARCODE:
            image = member_barcodes.get(placement.member_code)
            if not image:
                continue
            label = f'{placement.member_code} barcode'

        elif placement.kind == CodeKindChoices.ANCHOR_QR:
            image = anchor_qr
            label = 'Anchor QR'

        elif placement.kind == CodeKindChoices.QR:
            image = own_qr
            label = 'Summary QR'

        else:
            image = own_barcode
            label = 'Summary barcode'

        specs.append(
            StampSpec(
                image_png=image,
                pages=placement.resolved_pages(page_count),
                anchor=placement.anchor,
                offset_x=placement.offset_x,
                offset_y=placement.offset_y,
                width=placement.width,
                height=placement.height,
                opacity=placement.opacity,
                label=label,
            )
        )

    return specs


def summary_verification_payload(summary) -> str:
    """URL publica del resumen, contenido de su QR propio."""
    from .anchoring import summary_verification_url
    return summary_verification_url(summary)


@transaction.atomic
def certify_summary(summary, *, source_file=None, layout=None,
                    certificate_type=None, request=None):
    """
    Emite y certifica el documento del resumen.

    El resumen se guarda como un ``DocumentVerificationModel`` mas —con sus
    tres archivos y sus huellas— y ademas queda enlazado desdel resumen. Asi
    hereda gratis la verificacion por archivo, el registro de certificacion y
    la marca de agua.

    Parameters:
        summary: ``AegisSummaryModel`` ya sellado.
        source_file: el PDF del resumen sin codigos.
        layout: disposicion con las posiciones de los codigos de miembro.

    Returns:
        DocumentVerificationModel: el documento del resumen.
    """
    from apps.project.specific.documents.certificates.models import (
        DocumentCertificateTypeChoices, DocumentVerificationModel,
        SummaryStatusChoices)

    if not summary.master_hash:
        raise CertificationError(
            str(_('Seal the summary before issuing its document.'))
        )

    document = summary.summary_document

    if document is None:
        document = DocumentVerificationModel(
            document_title=summary.title,
            certificate_type=(
                certificate_type or DocumentCertificateTypeChoices.AEGIS
            ),
            issued_at=summary.issued_at or timezone.localdate(),
        )

    if layout is not None:
        document.stamp_layout = layout

    if source_file is not None:
        document.source_file = source_file

    document.save()

    # El codigo del resumen lleva el master hash en lugar del hash del propio
    # archivo: es lo que identifica a el resumen, no al papel.
    options = CodeOptions(
        include_nit=True,
        include_initials_sequence=True,
        include_document_hash=False,
        include_date=True,
        include_random_code=True,
    )

    outcome = certify_document(
        document,
        request=request,
        options=options,
        specs_builder=lambda doc, pages: build_summary_stamps(
            summary, doc.stamp_layout, pages
        ),
    )

    summary.summary_document = document
    summary.status = SummaryStatusChoices.CERTIFIED
    summary.save(update_fields=['summary_document', 'status', 'updated'])

    return document, outcome
