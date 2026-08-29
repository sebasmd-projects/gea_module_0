# apps/project/specific/internal/code_gen/services/samples.py
"""
Simbolos de ejemplo para la vista previa de disposicion.

La vista previa pintaba un rectangulo de color con el ancho y el alto
declarados, y eso enganaba: al estampar, ``pdf_stamp`` dibuja con
``preserveAspectRatio=True`` y ``anchor='sw'``, o sea que el simbolo se ajusta
*dentro* de la caja conservando su propia proporcion y se pega a la esquina
inferior izquierda. Declarar 320 pt de ancho no significa ocupar 320: si el
alto se queda corto, el simbolo se encoge y sobra ancho a la derecha.

Para que el operador vea eso antes de certificar hacen falta dos cosas: el
simbolo de verdad, y su proporcion natural. Ambas salen de aqui.

El QR de ejemplo apunta siempre a ``PUBLIC_BASE_URL`` porque es la unica base
de la que salen las URL permanentes -- nunca el host de la peticion.
"""

import logging
from io import BytesIO

from django.utils.translation import gettext_lazy as _
from PIL import Image

from ..constants import BARCODE_MAX_LENGTH, BARCODE_RECOMMENDED_MAX_LENGTH
from .codes import validate_barcode_payload
from .render import png_to_data_uri, render_barcode_png, render_qr_png

logger = logging.getLogger(__name__)

#: Longitud por defecto de la carga de ejemplo: la maxima recomendada para un
#: Code128 legible. Es el caso que interesa ver, porque es el mas ancho que se
#: deberia estampar.
BARCODE_SAMPLE_DEFAULT_LENGTH = BARCODE_RECOMMENDED_MAX_LENGTH

#: Limites de lo que tiene sentido pedir desde la interfaz. El maximo sale de
#: la propia validacion, no de un numero escrito aparte: pedir una muestra mas
#: larga de lo que Code128 acepta aqui daria una vista previa de algo que
#: despues seria imposible estampar.
BARCODE_SAMPLE_MIN_LENGTH = 8
BARCODE_SAMPLE_MAX_LENGTH = BARCODE_MAX_LENGTH

#: Alfabeto del relleno. Solo caracteres que Code128 admite y que
#: ``validate_barcode_payload`` no rechaza.
_FILLER = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'

#: La muestra viaja embebida en cada carga de la pagina, asi que se reduce
#: despues de dibujarla. Bajar el dpi del Code128 no vale: el modulo mide
#: 0,22 mm y por debajo de cierta resolucion no llega a un pixel, con lo que
#: la libreria falla al pintar la barra. Escalar la imagen ya hecha si es
#: seguro, y la proporcion -- lo unico que la vista previa necesita -- no
#: cambia.
_SAMPLE_MAX_PIXELS = 260


def clamp_length(value, default: int = BARCODE_SAMPLE_DEFAULT_LENGTH) -> int:
    """Deja la longitud pedida dentro de lo representable."""
    try:
        length = int(value)
    except (TypeError, ValueError):
        return default

    return max(BARCODE_SAMPLE_MIN_LENGTH, min(BARCODE_SAMPLE_MAX_LENGTH, length))


def sample_barcode_payload(length: int = BARCODE_SAMPLE_DEFAULT_LENGTH) -> str:
    """
    Una carga de ejemplo de exactamente ``length`` caracteres.

    Se construye repitiendo un alfabeto en vez de con caracteres iguales: un
    Code128 de 48 letras 'A' se comprime distinto que uno con variedad, y la
    gracia de la muestra es que se parezca a un codigo real.
    """
    length = clamp_length(length)
    repeats = (length // len(_FILLER)) + 1

    return (_FILLER * repeats)[:length]


def _shrink(png_bytes: bytes) -> bytes:
    """Reduce la muestra sin tocar su proporcion."""
    with Image.open(BytesIO(png_bytes)) as image:
        longest = max(image.width, image.height)

        if longest <= _SAMPLE_MAX_PIXELS:
            return png_bytes

        scale = _SAMPLE_MAX_PIXELS / longest
        resized = image.resize(
            (max(int(image.width * scale), 1),
             max(int(image.height * scale), 1)),
            Image.LANCZOS
        )

        # Un simbolo es blanco y negro, pero al reducirlo con LANCZOS aparecen
        # miles de grises de antialias que el PNG no sabe comprimir: el QR se
        # iba a 23 KB. Con una paleta de 16 baja a 2 KB y se ve igual.
        # FASTOCTREE es el unico metodo que acepta RGBA, y hace falta porque
        # la muestra es transparente.
        resized = resized.quantize(colors=16, method=Image.FASTOCTREE)

        buffer = BytesIO()
        resized.save(buffer, format='PNG', optimize=True)

        return buffer.getvalue()


def _natural_size(png_bytes: bytes):
    """Tamano en pixeles del PNG, que es lo que fija su proporcion."""
    with Image.open(BytesIO(png_bytes)) as image:
        return image.width, image.height


def _symbol(png_bytes: bytes, *, payload: str, note='') -> dict:
    # La proporcion se mide sobre el simbolo a tamano completo: redondear a los
    # pixeles de la miniatura desviaba la relacion un 1,5 %, y con ella el
    # tamano ocupado que la vista previa anuncia. La miniatura solo viaja.
    width, height = _natural_size(png_bytes)

    return {
        'src': png_to_data_uri(_shrink(png_bytes)),
        'natural_width': width,
        'natural_height': height,
        'ratio': (width / height) if height else 1.0,
        'payload': payload,
        'note': str(note),
    }


def qr_sample(payload: str = '') -> dict:
    """
    QR de ejemplo. Sin argumento apunta a la base publica de la plataforma.
    """
    from .certification import public_base_url

    payload = payload or public_base_url()

    return _symbol(
        render_qr_png(payload, transparent=True),
        payload=payload,
        note=_('Sample QR pointing to the platform.'),
    )


def barcode_sample(
    length: int = BARCODE_SAMPLE_DEFAULT_LENGTH,
    payload: str = ''
) -> dict:
    """
    Code128 de ejemplo.

    Con ``payload`` se dibuja el codigo real del documento; sin el, una carga
    de la longitud pedida. La diferencia importa: cuantos mas caracteres, mas
    estrecha es cada barra y mas alargado sale el simbolo.
    """
    if payload:
        try:
            payload = validate_barcode_payload(payload)
        except Exception:
            logger.warning('Sample barcode payload rejected; using filler')
            payload = ''

    if not payload:
        payload = sample_barcode_payload(length)
        note = _('Sample payload of %(count)s characters.') % {
            'count': len(payload)
        }
    else:
        note = _('Real code for this document.')

    return _symbol(
        render_barcode_png(payload, transparent=True),
        payload=payload,
        note=note,
    )


def sample_symbols(
    *,
    barcode_length: int = BARCODE_SAMPLE_DEFAULT_LENGTH,
    barcode_payload: str = '',
    qr_payload: str = ''
) -> dict:
    """
    Los dos simbolos que la vista previa sabe dibujar, por tipo de codigo.

    Las claves coinciden con ``CodeKindChoices`` para que el JS elija sin
    traducir nada.
    """
    qr = qr_sample(qr_payload)
    code = barcode_sample(barcode_length, barcode_payload)

    return {
        # Las claves son los valores de CodeKindChoices, no sus nombres.
        'QR': qr,
        'BARCODE': code,
        # El codigo de un miembro del resumen es un codigo de barras.
        'MEMBER': code,
        'ANCHOR': qr,
    }
