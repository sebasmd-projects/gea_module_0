# apps/project/specific/documents/certificates/files.py
"""
Entrega controlada de los archivos de certificacion.

Hasta ahora los tres PDF de cada documento colgaban de ``MEDIA_URL`` y los
servia el servidor web sin pasar por Django: cualquiera con la URL —o que la
adivinara— se los descargaba, incluido el **original sin codigos**. Toda la
proteccion OTP de la pagina de detalle se saltaba con un enlace directo.

Aqui viven las reglas de quien puede ver que:

============  ==========================================================
Archivo       Quien
============  ==========================================================
source        Solo personal interno. Es el original sin codigos: si sale,
              cualquiera tiene una version limpia del certificado.
certified     Solo personal interno. Es el que hace fe.
public        Quien haya superado la verificacion publica (OTP) o este
              autenticado. Es la copia distribuible.
============  ==========================================================

El servidor web debe dejar de servir ``MEDIA_ROOT/certificates`` por su
cuenta; si no, estas reglas son decorativas. Ver ``deploy/media.htaccess``.
"""

import logging
import mimetypes
import os
import unicodedata

from django.http import FileResponse, Http404
from django.utils.text import slugify

logger = logging.getLogger(__name__)

KIND_SOURCE = 'source'
KIND_CERTIFIED = 'certified'
KIND_PUBLIC = 'public'

FIELD_BY_KIND = {
    KIND_SOURCE: 'source_file',
    KIND_CERTIFIED: 'document_file',
    KIND_PUBLIC: 'public_copy_file',
}

# Los dos primeros no salen nunca de la casa.
INTERNAL_KINDS = (KIND_SOURCE, KIND_CERTIFIED)


def is_internal(user) -> bool:
    return bool(
        user
        and user.is_authenticated
        and user.is_active
        and (user.is_staff or user.is_superuser)
    )


def can_access(kind: str, user, has_otp_access: bool) -> bool:
    """Decide si quien pide puede llevarse este archivo."""
    if kind in INTERNAL_KINDS:
        return is_internal(user)

    if kind == KIND_PUBLIC:
        return bool(has_otp_access or (user and user.is_authenticated))

    return False


def download_name(document, kind: str) -> str:
    """
    Nombre con el que se descarga.

    Se construye del titulo, no de la ruta en disco: asi el nombre interno del
    archivo no filtra nada sobre como esta almacenado.
    """
    base = slugify(
        unicodedata.normalize('NFKD', document.document_title or 'documento')
    )[:80] or 'documento'

    suffix = {
        KIND_SOURCE: 'original',
        KIND_CERTIFIED: 'certificado',
        KIND_PUBLIC: 'copia',
    }.get(kind, kind)

    reference = document.public_code or str(document.pk)[:8]

    return f'{base}-{suffix}-{reference}.pdf'


def serve_field(file_field, *, filename: str, inline: bool = False) -> FileResponse:
    """
    Sirve un ``FieldFile`` cualquiera en streaming.

    Sin comprobar permisos: eso lo decide la vista, para que el criterio de
    acceso viva en un solo sitio.
    """
    if not file_field:
        raise Http404('file not set')

    try:
        handle = file_field.open('rb')
    except (FileNotFoundError, ValueError, OSError):
        logger.warning('Missing file on disk: %s', getattr(file_field, 'name', ''))
        raise Http404('file missing')

    content_type = (
        mimetypes.guess_type(os.path.basename(file_field.name))[0]
        or 'application/octet-stream'
    )

    response = FileResponse(
        handle,
        content_type=content_type,
        as_attachment=not inline,
        filename=filename,
    )
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def serve(document, kind: str) -> FileResponse:
    """
    Devuelve el archivo como respuesta en streaming.

    No comprueba permisos: eso es responsabilidad de la vista que llama, para
    que la decision de acceso quede en un solo sitio y sea evidente.
    """
    field_name = FIELD_BY_KIND.get(kind)

    if not field_name:
        raise Http404('unknown file kind')

    file_field = getattr(document, field_name, None)

    if not file_field:
        raise Http404('file not set')

    try:
        handle = file_field.open('rb')
    except (FileNotFoundError, ValueError, OSError):
        logger.warning(
            'Missing file on disk for document %s (%s)', document.pk, kind
        )
        raise Http404('file missing')

    content_type = (
        mimetypes.guess_type(os.path.basename(file_field.name))[0]
        or 'application/octet-stream'
    )

    response = FileResponse(
        handle,
        content_type=content_type,
        as_attachment=True,
        filename=download_name(document, kind),
    )

    # Estos archivos no deben quedarse en caches intermedias.
    response['Cache-Control'] = 'private, no-store, max-age=0'
    response['X-Content-Type-Options'] = 'nosniff'

    return response
