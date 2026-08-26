# apps/project/specific/internal/code_gen/services/watermark.py
"""
Marca de agua imperceptible pero verificable.

La copia distribuible lleva un identificador oculto en dos canales
independientes:

1. **Imagen oculta**: un XObject de imagen (RGB, 8 bits) incrustado en los
   recursos de cada pagina pero *nunca referenciado desde el flujo de
   contenido*. No se dibuja, no se imprime y no altera un solo pixel del
   documento; sin embargo esta fisicamente dentro del archivo y la plataforma
   puede extraerlo y mostrarlo.

2. **Clave privada en los metadatos** ``/Info``, como respaldo si un
   reprocesado del PDF descarta los recursos sin usar.

El contenido de ambos canales es el mismo token:

    GEAWM1|<uuid del documento>|<hmac-sha256(SECRET_KEY, uuid)[:16]>

El HMAC impide que un tercero fabrique una copia con marca valida sin
conocer la ``SECRET_KEY`` de la plataforma.
"""

import base64
import hashlib
import hmac
import logging
import math
from io import BytesIO
from typing import Optional

from django.conf import settings
from django.utils.crypto import constant_time_compare
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (DecodedStreamObject, DictionaryObject,
                           IndirectObject, NameObject, NumberObject)

from ..constants import (WATERMARK_HMAC_LENGTH, WATERMARK_INFO_KEY,
                         WATERMARK_MAGIC, WATERMARK_XOBJECT_NAME)

logger = logging.getLogger(__name__)

TOKEN_SEPARATOR = '|'


def _signature(reference: str) -> str:
    """HMAC-SHA256 truncado sobre la referencia del documento."""
    digest = hmac.new(
        key=settings.SECRET_KEY.encode('utf-8'),
        msg=f'{WATERMARK_MAGIC}:{reference}'.encode('utf-8'),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return digest[:WATERMARK_HMAC_LENGTH]


def build_token(reference: str) -> str:
    """Construye el token de marca de agua para un documento."""
    reference = str(reference)
    return TOKEN_SEPARATOR.join(
        (WATERMARK_MAGIC, reference, _signature(reference))
    )


def verify_token(token: str) -> Optional[str]:
    """
    Valida un token de marca de agua.

    Returns:
        str | None: la referencia del documento si la firma es valida.
    """
    if not token:
        return None

    parts = str(token).split(TOKEN_SEPARATOR)
    if len(parts) != 3:
        return None

    magic, reference, signature = parts

    if magic != WATERMARK_MAGIC:
        return None

    if not constant_time_compare(signature, _signature(reference)):
        return None

    return reference


# ==========================================================
# Codificacion del token dentro de una imagen RGB
# ==========================================================

def encode_token_image(token: str) -> tuple:
    """
    Empaqueta el token como muestras RGB de 8 bits.

    Formato: 2 bytes de longitud (big endian) + token en UTF-8 + relleno
    hasta completar pixeles enteros.

    Returns:
        tuple[bytes, int, int]: muestras, ancho y alto en pixeles.
    """
    payload = token.encode('utf-8')
    body = len(payload).to_bytes(2, 'big') + payload

    pixels = math.ceil(len(body) / 3)
    body = body.ljust(pixels * 3, b'\x00')

    return body, pixels, 1


def decode_token_image(samples: bytes) -> Optional[str]:
    """Recupera el token desde las muestras RGB. ``None`` si no es valido."""
    if not samples or len(samples) < 3:
        return None

    length = int.from_bytes(samples[:2], 'big')

    if length <= 0 or length > len(samples) - 2:
        return None

    try:
        return samples[2:2 + length].decode('utf-8')
    except UnicodeDecodeError:
        return None


# ==========================================================
# Insercion y extraccion en el PDF
# ==========================================================

def embed_watermark(source: bytes, token: str) -> bytes:
    """
    Devuelve una copia del PDF con la marca de agua oculta incrustada.

    El contenido visible del documento no se modifica.
    """
    writer = PdfWriter(clone_from=BytesIO(source))

    samples, width, height = encode_token_image(token)

    image_stream = DecodedStreamObject()
    image_stream.set_data(samples)
    image_stream[NameObject('/Type')] = NameObject('/XObject')
    image_stream[NameObject('/Subtype')] = NameObject('/Image')
    image_stream[NameObject('/Width')] = NumberObject(width)
    image_stream[NameObject('/Height')] = NumberObject(height)
    image_stream[NameObject('/ColorSpace')] = NameObject('/DeviceRGB')
    image_stream[NameObject('/BitsPerComponent')] = NumberObject(8)

    reference = writer._add_object(image_stream)

    name = NameObject(WATERMARK_XOBJECT_NAME)

    for page in writer.pages:
        resources = page.get('/Resources')

        if isinstance(resources, IndirectObject):
            resources = resources.get_object()

        if resources is None:
            resources = DictionaryObject()
            page[NameObject('/Resources')] = resources

        xobjects = resources.get('/XObject')

        if isinstance(xobjects, IndirectObject):
            xobjects = xobjects.get_object()

        if xobjects is None:
            xobjects = DictionaryObject()
            resources[NameObject('/XObject')] = xobjects

        xobjects[name] = reference

    writer.add_metadata({WATERMARK_INFO_KEY: token})

    output = BytesIO()
    writer.write(output)
    writer.close()

    return output.getvalue()


def extract_watermark_samples(source: bytes) -> Optional[bytes]:
    """Devuelve las muestras crudas de la imagen oculta, si existe."""
    try:
        reader = PdfReader(BytesIO(source))
    except Exception:
        return None

    for page in reader.pages:
        try:
            resources = page.get('/Resources')

            if isinstance(resources, IndirectObject):
                resources = resources.get_object()

            if not resources:
                continue

            xobjects = resources.get('/XObject')

            if isinstance(xobjects, IndirectObject):
                xobjects = xobjects.get_object()

            if not xobjects or WATERMARK_XOBJECT_NAME not in xobjects:
                continue

            stream = xobjects[WATERMARK_XOBJECT_NAME]

            if isinstance(stream, IndirectObject):
                stream = stream.get_object()

            return stream.get_data()

        except Exception:
            logger.exception('Could not read the hidden watermark image')
            continue

    return None


def extract_token(source: bytes) -> Optional[str]:
    """
    Extrae el token de marca de agua probando los dos canales.

    Returns:
        str | None: el token tal cual estaba en el archivo (sin verificar).
    """
    samples = extract_watermark_samples(source)

    if samples:
        token = decode_token_image(samples)
        if token:
            return token

    try:
        reader = PdfReader(BytesIO(source))
        metadata = reader.metadata or {}
        token = metadata.get(WATERMARK_INFO_KEY)
        if token:
            return str(token)
    except Exception:
        logger.exception('Could not read the watermark metadata key')

    return None


def read_watermark_reference(source: bytes) -> Optional[str]:
    """Extrae y valida la marca. Devuelve la referencia del documento."""
    return verify_token(extract_token(source))


def watermark_preview_png(source: bytes) -> Optional[str]:
    """
    Renderiza la imagen oculta como PNG ampliado, para mostrarla en la
    plataforma como evidencia visual de la marca.

    Returns:
        str | None: data URI del PNG.
    """
    samples = extract_watermark_samples(source)

    if not samples:
        return None

    try:
        from PIL import Image

        width = len(samples) // 3
        image = Image.frombytes('RGB', (width, 1), samples[:width * 3])
        image = image.resize((width * 6, 48), Image.NEAREST)

        buffer = BytesIO()
        image.save(buffer, format='PNG')

        return (
            'data:image/png;base64,'
            f'{base64.b64encode(buffer.getvalue()).decode()}'
        )
    except Exception:
        logger.exception('Could not render the watermark preview')
        return None
