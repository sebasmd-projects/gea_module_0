# apps/project/specific/internal/code_gen/services/certification.py
"""
Motor de certificacion documental.

Resuelve la dependencia circular entre el hash y el codigo de barras:

    el hash del archivo estampado no existe hasta que se estampa,
    pero el codigo estampado deberia contener un hash.

La regla adoptada es que **el codigo certifica el contenido que se
certifico**, es decir, el hash del archivo ORIGINAL sin simbolos. Con eso el
codigo se puede componer antes de estampar, y una vez estampado se calculan y
almacenan los hashes de los otros dos archivos. La cadena queda:

    original  --(hash A)-->  codigo con hash A  --(estampado)-->  certificado
    certificado  --(hash B)-->  registro
    certificado  --(marca de agua)-->  copia publica  --(hash C)-->  registro

Los tres hashes quedan guardados, de modo que cualquiera de los tres archivos
se puede reconocer luego por su huella.
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

from django.core.files.base import ContentFile
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from ..constants import (CERTIFIABLE_EXTENSIONS, DEFAULT_BARCODE_HEIGHT_PT,
                         DEFAULT_BARCODE_WIDTH_PT, DEFAULT_MARGIN_PT,
                         DEFAULT_QR_SIZE_PT, HASH_B64_DEFAULT_LENGTH,
                         RANDOM_CODE_DEFAULT_LENGTH)
from .codes import (build_code_payload, derive_initials, generate_random_code,
                    next_sequence, validate_barcode_payload)
from .hashing import canonical_pdf_hash, hash_to_base64, read_all_bytes, sha256_hex
from .pdf_stamp import StampSpec, pdf_page_count, stamp_pdf
from .render import render_barcode_png, render_qr_png
from .watermark import build_token, embed_watermark

logger = logging.getLogger(__name__)


class CertificationError(Exception):
    """Error de negocio durante la certificacion."""


@dataclass
class CodeOptions:
    """
    Que segmentos entran en el codigo.

    Los valores por defecto reproducen el formato completo:

        NIT  INICIALES_SECUENCIA  HASH  FECHA  ALEATORIO(12)
    """

    include_nit: bool = True
    custom_text: str = ''
    include_initials_sequence: bool = True
    initials: str = ''
    include_document_hash: bool = True
    hash_fragment_length: int = HASH_B64_DEFAULT_LENGTH
    include_date: bool = True
    include_random_code: bool = True
    random_code_length: int = RANDOM_CODE_DEFAULT_LENGTH


@dataclass
class CertificationOutcome:
    code_payload: str = ''
    qr_payload: str = ''
    page_count: int = 0
    applied: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    registration: object = None


# ==========================================================
# URL publica
# ==========================================================

def public_base_url() -> str:
    """
    Base canonica del sitio, siempre ``PUBLIC_BASE_URL``.

    Deliberadamente NO se deriva de la peticion. El QR queda estampado dentro
    de un PDF que vivira anos y circulara fuera de aqui: si se construyera con
    el host de la peticion, certificar desde ``runserver`` en la LAN grabaria
    para siempre un ``http://192.168.x.x:8000`` dentro del documento. Lo mismo
    vale para la URL del registro de certificacion.
    """
    from django.conf import settings

    return str(
        getattr(
            settings,
            'PUBLIC_BASE_URL',
            'https://geausa.propensionesabogados.com'
        )
    ).rstrip('/')


def build_verification_url(document) -> str:
    """URL publica de verificacion del documento (contenido del QR)."""
    path = reverse(
        'certificates:detail_document_verification_aegis',
        kwargs={'pk': document.pk}
    )
    return f'{public_base_url()}{path}'


# ==========================================================
# Estampado
# ==========================================================

def default_stamp_specs(barcode_png: bytes, qr_png: bytes, page_count: int) -> List[StampSpec]:
    """Posiciones por defecto cuando el documento no tiene layout asignado."""
    last = [page_count - 1] if page_count else []

    return [
        StampSpec(
            image_png=qr_png,
            pages=last,
            anchor='BR',
            offset_x=DEFAULT_MARGIN_PT,
            offset_y=DEFAULT_MARGIN_PT,
            width=DEFAULT_QR_SIZE_PT,
            height=DEFAULT_QR_SIZE_PT,
            label='QR (default, last page)',
        ),
        StampSpec(
            image_png=barcode_png,
            pages=last,
            anchor='BC',
            offset_x=0.0,
            offset_y=DEFAULT_MARGIN_PT,
            width=DEFAULT_BARCODE_WIDTH_PT,
            height=DEFAULT_BARCODE_HEIGHT_PT,
            label='Barcode (default, last page)',
        ),
    ]


def build_stamp_specs(layout, barcode_png: bytes, qr_png: bytes, page_count: int) -> List[StampSpec]:
    """Traduce un ``StampLayoutModel`` a especificaciones de estampado."""
    if layout is None:
        return default_stamp_specs(barcode_png, qr_png, page_count)

    from ..models import CodeKindChoices

    specs: List[StampSpec] = []

    for placement in layout.placements.filter(is_active=True):
        image = (
            qr_png
            if placement.kind == CodeKindChoices.QR
            else barcode_png
        )

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
                label=(
                    f"{placement.get_kind_display()} - "
                    f'{placement.get_page_selector_display()}'
                ),
            )
        )

    if not specs:
        return default_stamp_specs(barcode_png, qr_png, page_count)

    return specs


# ==========================================================
# Pipeline
# ==========================================================

def _validate_source(document) -> bytes:
    if not document.source_file:
        raise CertificationError(
            str(_('Upload the original document (without codes) first.'))
        )

    name = str(document.source_file.name or '').lower()

    if not name.endswith(CERTIFIABLE_EXTENSIONS):
        raise CertificationError(
            str(
                _('Only these formats can be certified: %(formats)s.')
                % {'formats': ', '.join(CERTIFIABLE_EXTENSIONS)}
            )
        )

    data = read_all_bytes(document.source_file)

    if not data[:5].startswith(b'%PDF'):
        raise CertificationError(
            str(_('The uploaded file is not a readable PDF.'))
        )

    return data


@transaction.atomic
def certify_document(
    document,
    *,
    request=None,
    issue_date: Optional[date] = None,
    options: Optional[CodeOptions] = None,
    qr_payload: Optional[str] = None,
):
    """
    Ejecuta la certificacion completa de un documento.

    Genera los tres archivos (original, certificado y copia publica), sus
    huellas y el codigo asociado, y deja el documento en estado CERTIFIED.

    Parameters:
        document: instancia de ``DocumentVerificationModel``.
        request: peticion actual, para construir la URL absoluta del QR.
        issue_date: fecha a incrustar en el codigo (por defecto, la de emision).
        options: que segmentos entran en el codigo.
        qr_payload: contenido del QR; por defecto la URL publica del documento.

    Returns:
        CertificationOutcome
    """
    from apps.project.specific.documents.certificates.models import \
        CertificationStatusChoices

    options = options or CodeOptions()

    source_bytes = _validate_source(document)

    # ---- 1. Huellas del original ------------------------------------
    source_hash = sha256_hex(source_bytes)
    source_content_hash = canonical_pdf_hash(source_bytes) or ''

    # ---- 2. Identidad y codigo --------------------------------------
    if not document.public_code:
        document.public_code = generate_random_code(
            options.random_code_length or RANDOM_CODE_DEFAULT_LENGTH
        )

    if not document.code_initials:
        document.code_initials = (
            options.initials
            or derive_initials(document.document_title)
        )

    if not document.code_sequence:
        document.code_sequence = next_sequence()

    hash_fragment = hash_to_base64(
        source_hash,
        options.hash_fragment_length or HASH_B64_DEFAULT_LENGTH
    )

    code_payload = build_code_payload(
        include_nit=options.include_nit,
        custom_text=options.custom_text,
        initials=(
            document.code_initials
            if options.include_initials_sequence else ''
        ),
        sequence=(
            document.code_sequence
            if options.include_initials_sequence else ''
        ),
        hash_fragment=hash_fragment if options.include_document_hash else '',
        issue_date=(
            (issue_date or document.issued_at or timezone.localdate())
            if options.include_date else None
        ),
        random_code=(
            document.public_code if options.include_random_code else ''
        ),
    )

    validate_barcode_payload(code_payload)

    qr_payload = qr_payload or build_verification_url(document)

    # ---- 3. Simbolos --------------------------------------------------
    barcode_png = render_barcode_png(code_payload)
    qr_png = render_qr_png(qr_payload)

    # ---- 4. Estampado -------------------------------------------------
    page_count = pdf_page_count(source_bytes)

    specs = build_stamp_specs(
        document.stamp_layout,
        barcode_png,
        qr_png,
        page_count
    )

    certified_bytes, report = stamp_pdf(source_bytes, specs)

    # ---- 5. Copia publica con marca de agua oculta ---------------------
    watermark_token = build_token(document.pk)
    public_bytes = embed_watermark(certified_bytes, watermark_token)

    # ---- 6. Persistencia ----------------------------------------------
    base_name = f'{document.pk}.pdf'

    document.source_hash = source_hash
    document.source_content_hash = source_content_hash

    document.document_file.save(
        f'certified_{base_name}',
        ContentFile(certified_bytes),
        save=False
    )
    document.document_hash = sha256_hex(certified_bytes)
    document.certified_content_hash = canonical_pdf_hash(certified_bytes) or ''

    document.public_copy_file.save(
        f'public_{base_name}',
        ContentFile(public_bytes),
        save=False
    )
    document.public_copy_hash = sha256_hex(public_bytes)
    document.public_copy_content_hash = canonical_pdf_hash(public_bytes) or ''

    document.watermark_token = watermark_token
    document.code_payload = code_payload
    document.code_hash_fragment = hash_fragment
    document.qr_payload = qr_payload
    document.certification_status = CertificationStatusChoices.CERTIFIED
    document.certified_at = timezone.now()

    document.save()

    registration = _register_code(
        document, code_payload, qr_payload, source_hash, hash_fragment
    )

    return CertificationOutcome(
        code_payload=code_payload,
        qr_payload=qr_payload,
        page_count=report.page_count,
        applied=report.applied,
        skipped=report.skipped,
        registration=registration,
    )


def _register_code(document, code_payload, qr_payload, source_hash, hash_fragment):
    """Deja traza del codigo emitido en el registro historico del generador."""
    from ..models import CodeRegistrationModel

    return CodeRegistrationModel.objects.create(
        document=document,
        reference=document.document_title[:100],
        description=str(
            _('Automatic certification of document %(pk)s')
            % {'pk': document.pk}
        ),
        code_information=code_payload,
        initials=document.code_initials,
        sequence=document.code_sequence,
        random_code=document.public_code,
        source_file_hash=source_hash,
        hash_fragment=hash_fragment,
        generated_barcode=True,
        generated_qr=True,
        qr_payload=qr_payload,
    )
