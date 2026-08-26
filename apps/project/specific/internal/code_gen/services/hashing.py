# apps/project/specific/internal/code_gen/services/hashing.py
"""
Huellas digitales de archivos.

Se manejan dos niveles de huella por archivo:

- ``raw`` (SHA-256 sobre los bytes exactos): la mas fuerte. Cualquier
  cambio, incluido un simple reguardado del PDF, la invalida.

- ``canonical`` (SHA-256 sobre el contenido renderizable del PDF): ignora
  metadatos de documento (/Info: Title, Author, Producer, CreationDate,
  ModDate), el /ID del archivo y la estructura fisica (xref, numeracion de
  objetos, linealizacion). Sirve para reconocer una copia cuyo transporte
  (correo, gestores documentales, reguardados) altero los metadatos pero no
  el contenido.

  Tambien ignora deliberadamente el recurso de la marca de agua oculta, de
  modo que el documento certificado y su copia distribuible comparten
  ``canonical``: lo unico que los separa es la marca. Eso permite comprobar
  la integridad del contenido de la copia sin depender de la marca, y usar la
  marca solo para distinguir cual de los dos archivos se recibio.
"""

import base64
import hashlib
from io import BytesIO
from typing import Optional, Union

from pypdf import PdfReader
from pypdf.generic import IndirectObject

from ..constants import WATERMARK_XOBJECT_NAME

CHUNK_SIZE = 1024 * 1024

FileLike = Union[bytes, bytearray, "object"]


def _iter_chunks(source):
    """Itera en bloques sobre bytes, ficheros Django o file-like objects."""
    if isinstance(source, (bytes, bytearray)):
        yield bytes(source)
        return

    chunks = getattr(source, 'chunks', None)
    if callable(chunks):
        try:
            source.seek(0)
        except Exception:
            pass
        for chunk in source.chunks(CHUNK_SIZE):
            yield chunk
        return

    try:
        source.seek(0)
    except Exception:
        pass

    while True:
        chunk = source.read(CHUNK_SIZE)
        if not chunk:
            break
        yield chunk


def read_all_bytes(source) -> bytes:
    """Devuelve el contenido completo de un archivo/bytes como ``bytes``."""
    if isinstance(source, (bytes, bytearray)):
        return bytes(source)
    return b''.join(_iter_chunks(source))


def sha256_hex(source) -> str:
    """SHA-256 en hexadecimal sobre los bytes exactos del archivo."""
    digest = hashlib.sha256()
    for chunk in _iter_chunks(source):
        digest.update(chunk)
    return digest.hexdigest()


def sha256_digest(source) -> bytes:
    """SHA-256 en bytes crudos (32 bytes)."""
    digest = hashlib.sha256()
    for chunk in _iter_chunks(source):
        digest.update(chunk)
    return digest.digest()


def hash_to_base64(hex_or_bytes, length: Optional[int] = None) -> str:
    """
    Convierte un digest SHA-256 a base64 urlsafe sin relleno.

    Se usa el alfabeto urlsafe (``-`` y ``_`` en vez de ``+`` y ``/``) para que
    el resultado sea valido tanto dentro de un codigo de barras Code128 como
    dentro de una URL.
    """
    if isinstance(hex_or_bytes, str):
        raw = bytes.fromhex(hex_or_bytes)
    else:
        raw = bytes(hex_or_bytes)

    encoded = base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')

    if length:
        return encoded[:length]

    return encoded


def _stream_fingerprint(obj, digest, seen: set) -> None:
    """Agrega al digest los bytes crudos (aun codificados) de un stream."""
    if isinstance(obj, IndirectObject):
        key = (obj.idnum, obj.generation)
        if key in seen:
            digest.update(b'<ref>')
            return
        seen.add(key)
        obj = obj.get_object()

    raw = getattr(obj, '_data', None)
    if raw is None:
        try:
            raw = obj.get_data()
        except Exception:
            raw = b''

    digest.update(len(raw).to_bytes(8, 'big'))
    digest.update(raw if isinstance(raw, (bytes, bytearray)) else b'')


def canonical_pdf_hash(source) -> Optional[str]:
    """
    Huella del contenido renderizable de un PDF.

    Recorre paginas en orden y acumula: caja de la pagina, rotacion, bytes del
    flujo de contenido y bytes de cada XObject referenciado (imagenes y
    formularios), ordenados por nombre de recurso.

    Returns:
        str | None: hexdigest, o ``None`` si el archivo no es un PDF legible.
    """
    data = read_all_bytes(source)

    if not data[:5].startswith(b'%PDF'):
        return None

    try:
        reader = PdfReader(BytesIO(data))
    except Exception:
        return None

    digest = hashlib.sha256()
    digest.update(b'GEA-PDF-CANONICAL-V1')

    try:
        pages = reader.pages
    except Exception:
        return None

    for index, page in enumerate(pages):
        seen: set = set()

        digest.update(f'|page:{index}|'.encode('ascii'))

        try:
            box = page.mediabox
            digest.update(
                f'{float(box.left):.4f},{float(box.bottom):.4f},'
                f'{float(box.right):.4f},{float(box.top):.4f}'.encode('ascii')
            )
        except Exception:
            digest.update(b'nobox')

        digest.update(str(page.get('/Rotate', 0)).encode('ascii'))

        contents = page.get('/Contents')
        if contents is not None:
            if isinstance(contents, IndirectObject):
                contents = contents.get_object()

            if isinstance(contents, list):
                for item in contents:
                    _stream_fingerprint(item, digest, seen)
            else:
                _stream_fingerprint(contents, digest, seen)

        try:
            resources = page.get('/Resources')
            if isinstance(resources, IndirectObject):
                resources = resources.get_object()

            xobjects = resources.get('/XObject') if resources else None
            if isinstance(xobjects, IndirectObject):
                xobjects = xobjects.get_object()

            if xobjects:
                for name in sorted(xobjects.keys()):
                    if str(name) == WATERMARK_XOBJECT_NAME:
                        continue
                    digest.update(str(name).encode('ascii', 'ignore'))
                    _stream_fingerprint(xobjects[name], digest, seen)
        except Exception:
            digest.update(b'noxobject')

    return digest.hexdigest()


def file_fingerprints(source) -> dict:
    """
    Calcula de una sola pasada las dos huellas de un archivo.

    Returns:
        dict: ``{'raw': str, 'canonical': str | None, 'size': int}``
    """
    data = read_all_bytes(source)
    return {
        'raw': sha256_hex(data),
        'canonical': canonical_pdf_hash(data),
        'size': len(data),
    }
