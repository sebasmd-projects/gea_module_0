# apps/project/specific/internal/code_gen/services/render.py
"""
Renderizado de los simbolos: Code128 y QR.

Todas las funciones devuelven ``bytes`` PNG para que sirvan indistintamente
para incrustar en un PDF, guardar en disco o exponer como data URI.

**El fondo es transparente por defecto**, y eso no siempre fue asi. Antes lo
transparente habia que pedirlo, y solo lo pedia la vista previa: todo lo que
se estampaba de verdad salia con un rectangulo blanco debajo que tapaba el
diseño del documento. La vista previa enseñaba una cosa y el papel traia otra.

Con el fondo transparente hay que colocar los codigos sobre zonas claras del
documento -- un Code128 con las barras negras sobre un fondo oscuro no lo lee
ningun escaner. Para eso esta el editor de disposiciones, y ahora la vista
previa dibuja exactamente lo que se va a estampar, asi que el riesgo se ve
antes de emitir.
"""

import base64
import logging
from io import BytesIO
from typing import Optional

import barcode
import qrcode
from barcode.writer import ImageWriter
from django.contrib.staticfiles import finders
from PIL import Image

from .codes import validate_barcode_payload

logger = logging.getLogger(__name__)

DEFAULT_LOGO_STATIC_PATH = 'assets/imgs/favicons/favicon_gea.webp'

BARCODE_WRITER_OPTIONS = {
    'module_width': 0.22,
    'module_height': 14.0,
    'font_size': 8,
    'text_distance': 3.0,
    'quiet_zone': 3.0,
    'write_text': True,
    'dpi': 300,
}


def png_to_data_uri(png_bytes: bytes) -> str:
    """Convierte bytes PNG en un data URI listo para un ``<img src>``."""
    return f'data:image/png;base64,{base64.b64encode(png_bytes).decode()}'


def render_barcode_png(
    text: str,
    *,
    transparent: bool = True,
    options: Optional[dict] = None
) -> bytes:
    """
    Genera un Code128 a partir de un texto ya validado.

    Raises:
        ValidationError: si el texto no es representable en Code128.
    """
    text = validate_barcode_payload(text)

    writer_options = dict(BARCODE_WRITER_OPTIONS)
    if options:
        writer_options.update(options)

    buffer = BytesIO()
    barcode_class = barcode.get_barcode_class('code128')
    barcode_class(text, writer=ImageWriter()).write(buffer, writer_options)
    buffer.seek(0)

    image = Image.open(buffer).convert('RGBA')

    if transparent:
        pixels = [
            (255, 255, 255, 0) if pixel[:3] == (255, 255, 255) else pixel
            for pixel in image.getdata()
        ]
        image.putdata(pixels)

    output = BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


def render_qr_png(
    text: str,
    *,
    transparent: bool = True,
    logo_static_path: str = DEFAULT_LOGO_STATIC_PATH,
    box_size: int = 10,
    border: int = 4
) -> bytes:
    """
    Genera un QR con correccion de errores alta y el logo institucional.

    El QR admite cualquier contenido, incluidas URLs completas: es el canal
    indicado para todo lo que el codigo de barras no puede representar.
    """
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=box_size,
        border=border,
    )
    qr.add_data(text)
    qr.make(fit=True)

    image = qr.make_image(
        fill_color='black',
        back_color='transparent' if transparent else 'white',
    ).convert('RGBA')

    if logo_static_path:
        try:
            logo_path = finders.find(logo_static_path)

            if not logo_path:
                raise FileNotFoundError(
                    f'Static file not found: {logo_static_path}'
                )

            icon = Image.open(logo_path).convert('RGBA')
            size = image.size[0] // 5
            icon = icon.resize((size, size), Image.LANCZOS)

            position = (
                (image.size[0] - size) // 2,
                (image.size[1] - size) // 2,
            )
            image.paste(icon, position, mask=icon.split()[3])

        except Exception:
            logger.exception('Could not overlay the institutional logo on the QR')

    output = BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()
