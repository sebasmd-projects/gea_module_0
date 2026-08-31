# apps/project/specific/documents/certificates/verification.py
"""
Cotejo de un archivo subido contra los documentos certificados.

Se prueban tres canales, del mas estricto al mas tolerante:

1. **Huella exacta** (SHA-256 de los bytes del archivo). Reconoce el original,
   el certificado o la copia distribuible byte a byte.

2. **Huella de contenido** (SHA-256 del contenido renderizable del PDF, sin
   contar la marca de agua). Reconoce el mismo documento cuando el transporte
   altero los metadatos (/Info, /ID) o reescribio la estructura del archivo,
   pero no una sola pagina, imagen o linea de texto. Como el certificado y su
   copia distribuible comparten esta huella, se distinguen entre si por la
   presencia de la marca de agua.

3. **Marca de agua oculta**. Si el contenido ya no coincide pero la marca sigue
   ahi con su firma HMAC valida, el archivo salio de la plataforma pero fue
   modificado: NO es una copia valida, y asi se informa.

Si ningun canal responde, el archivo no corresponde a un documento
certificado.
"""

import logging
import uuid as uuid_module
from dataclasses import dataclass
from typing import Optional

from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.project.specific.internal.code_gen.services.hashing import (
    canonical_pdf_hash, read_all_bytes, sha256_hex)
from apps.project.specific.internal.code_gen.services.watermark import \
    read_watermark_reference

from .models import (AegisSummaryModel, DocumentCopyKind,
                     DocumentVerificationModel)

logger = logging.getLogger(__name__)

MATCH_EXACT = 'EXACT'
MATCH_CONTENT = 'CONTENT'
MATCH_TAMPERED = 'TAMPERED'


@dataclass
class FileMatch:
    """Resultado del cotejo de un archivo."""

    document: Optional[DocumentVerificationModel]
    copy_kind: str
    match_level: str
    file_hash: str
    content_hash: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        """Solo un cotejo por huella acredita el archivo."""
        return self.match_level in (MATCH_EXACT, MATCH_CONTENT)

    @property
    def is_exact(self) -> bool:
        return self.match_level == MATCH_EXACT

    @property
    def is_original(self) -> bool:
        return self.copy_kind == DocumentCopyKind.SOURCE

    @property
    def is_distributable_copy(self) -> bool:
        return self.copy_kind == DocumentCopyKind.PUBLIC_COPY

    def as_session_payload(self) -> dict:
        return {
            'document_id': str(self.document.pk) if self.document else '',
            'copy_kind': self.copy_kind,
            'match_level': self.match_level,
            'file_hash': self.file_hash,
        }


def _has_valid_watermark(data: bytes) -> bool:
    return read_watermark_reference(data) is not None


def _kind_for_exact_hash(document, file_hash: str) -> Optional[str]:
    if file_hash and file_hash == document.public_copy_hash:
        return DocumentCopyKind.PUBLIC_COPY
    if file_hash and file_hash == document.document_hash:
        return DocumentCopyKind.CERTIFIED
    if file_hash and file_hash == document.source_hash:
        return DocumentCopyKind.SOURCE
    return None


def _kind_for_content_hash(document, content_hash: str, watermarked: bool) -> Optional[str]:
    """
    El certificado y su copia comparten huella de contenido: los separa la
    marca de agua.
    """
    if content_hash and content_hash == document.source_content_hash:
        return DocumentCopyKind.SOURCE

    if content_hash and content_hash in (
        document.certified_content_hash,
        document.public_copy_content_hash,
    ):
        return (
            DocumentCopyKind.PUBLIC_COPY
            if watermarked
            else DocumentCopyKind.CERTIFIED
        )

    return None


def identify_uploaded_document(uploaded_file) -> Optional[FileMatch]:
    """
    Identifica a que documento certificado corresponde un archivo.

    Parameters:
        uploaded_file: ``UploadedFile`` o ``bytes``.

    Returns:
        FileMatch | None: ``None`` si el archivo no guarda relacion alguna con
        la plataforma. Un ``FileMatch`` con ``is_valid`` en falso significa que
        el archivo salio de la plataforma pero fue modificado.
    """
    data = read_all_bytes(uploaded_file)

    if not data:
        return None

    file_hash = sha256_hex(data)

    document = (
        DocumentVerificationModel.objects
        .filter(is_active=True)
        .filter(
            Q(source_hash=file_hash)
            | Q(document_hash=file_hash)
            | Q(public_copy_hash=file_hash)
        )
        .first()
    )

    if document:
        copy_kind = _kind_for_exact_hash(document, file_hash)
        if copy_kind:
            return FileMatch(
                document=document,
                copy_kind=copy_kind,
                match_level=MATCH_EXACT,
                file_hash=file_hash,
            )

    content_hash = canonical_pdf_hash(data)
    watermarked = _has_valid_watermark(data)

    if content_hash:
        document = (
            DocumentVerificationModel.objects
            .filter(is_active=True)
            .filter(
                Q(source_content_hash=content_hash)
                | Q(certified_content_hash=content_hash)
                | Q(public_copy_content_hash=content_hash)
            )
            .first()
        )

        if document:
            copy_kind = _kind_for_content_hash(
                document,
                content_hash,
                watermarked
            )
            if copy_kind:
                return FileMatch(
                    document=document,
                    copy_kind=copy_kind,
                    match_level=MATCH_CONTENT,
                    file_hash=file_hash,
                    content_hash=content_hash,
                )

    reference = read_watermark_reference(data)

    if reference:
        document = (
            DocumentVerificationModel.objects
            .filter(pk=reference, is_active=True)
            .first()
        )

        return FileMatch(
            document=document,
            copy_kind=DocumentCopyKind.WATERMARK,
            match_level=MATCH_TAMPERED,
            file_hash=file_hash,
            content_hash=content_hash,
        )

    return None


def find_document_by_identifier(identifier: str, certificate_type: str = None):
    """
    Busca un documento por codigo publico, prefijo de UUID o UUID completo.

    No depende de la longitud del identificador: prueba los tres campos.
    """
    queryset = DocumentVerificationModel.objects.all()

    if certificate_type:
        queryset = queryset.filter(certificate_type=certificate_type)

    normalized = (identifier or '').strip()

    if not normalized:
        return None

    lookup = (
        Q(public_code__iexact=normalized)
        | Q(uuid_prefix__iexact=normalized)
    )

    try:
        lookup |= Q(pk=uuid_module.UUID(normalized))
    except (ValueError, AttributeError, TypeError):
        pass

    return queryset.filter(lookup).first()


def find_summary_by_identifier(identifier: str):
    """
    Busca un **resumen** por su codigo publico, prefijo de UUID o UUID.

    Un resumen tambien es una cosa certificada con un codigo publico impreso,
    pero vive en su propia tabla (``apps_certificates_aegis_summary``), no en
    la de documentos. El formulario publico solo miraba la de documentos, asi
    que quien tecleaba el codigo de un resumen recibia "Document not found"
    aunque el codigo fuera correcto y estuviera impreso en el papel que tenia
    delante.

    Quien lee un codigo no sabe --ni tiene por que saber-- en que tabla se
    guarda. Un identificador es un identificador.

    Returns:
        AegisSummaryModel | None
    """
    normalized = (identifier or '').strip()

    if not normalized:
        return None

    lookup = (
        Q(public_code__iexact=normalized)
        | Q(uuid_prefix__iexact=normalized)
    )

    try:
        lookup |= Q(pk=uuid_module.UUID(normalized))
    except (ValueError, AttributeError, TypeError):
        pass

    return AegisSummaryModel.objects.filter(lookup).first()


def resolve_identifier(identifier: str, certificate_type: str = None):
    """
    Resuelve un identificador a lo que sea que designe.

    Primero un documento, que es el caso comun; despues un resumen. El orden
    importa poco --los codigos no se solapan-- pero fijarlo evita que el
    resultado dependa del azar si algun dia se solaparan.

    Returns:
        tuple[str, object] | tuple[None, None]: ``('document', doc)``,
        ``('summary', summary)``, o ``(None, None)`` si no hay nada.
    """
    document = find_document_by_identifier(identifier, certificate_type)

    if document is not None:
        return 'document', document

    summary = find_summary_by_identifier(identifier)

    if summary is not None:
        return 'summary', summary

    return None, None
