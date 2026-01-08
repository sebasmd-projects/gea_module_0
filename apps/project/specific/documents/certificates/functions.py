import base64
import hashlib
import logging
from io import BytesIO

import barcode
import qrcode
import requests
from barcode.writer import ImageWriter
from PIL import Image

logging = logging.getLogger(__name__)


def get_file_hash(django_file):
    sha256 = hashlib.sha256()
    for chunk in django_file.chunks():
        sha256.update(chunk)
    return sha256.hexdigest()


def generate_qr_with_favicon(text_data: str, image_url: str = "https://geausa.propensionesabogados.com/static/assets/imgs/brands/aegis_logo.webp"):
    qr = qrcode.QRCode(version=1,error_correction=qrcode.constants.ERROR_CORRECT_H,box_size=10,border=4)
    qr.add_data(text_data)
    qr.make(fit=True)

    # QR transparente real
    img_qr = qr.make_image(fill_color=(0, 0, 0, 255),back_color=(0, 0, 0, 0)).convert("RGBA")

    try:
        response = requests.get(image_url, timeout=5)
        response.raise_for_status()

        icon = Image.open(BytesIO(response.content)).convert("RGBA")

        icon_size = img_qr.size[0] // 5
        icon = icon.resize((icon_size, icon_size), Image.LANCZOS)

        padding = 12
        box_size = icon_size + padding * 2
        overlay = Image.new("RGBA", (box_size, box_size), (255, 255, 255, 0))

        overlay.paste(icon, (padding, padding), mask=icon)

        pos = (
            (img_qr.size[0] - box_size) // 2,
            (img_qr.size[1] - box_size) // 2
        )

        img_qr.alpha_composite(overlay, dest=pos)

    except Exception as e:
        logging.error("QR favicon error", exc_info=e)

    buffer = BytesIO()
    img_qr.save(buffer, format="PNG")
    qr_base64 = base64.b64encode(buffer.getvalue()).decode()

    return f"data:image/png;base64,{qr_base64}"



def generate_barcode(custom_text: str):
    buffer = BytesIO()
    barcode_class = barcode.get_barcode_class('code128')
    barcode_image = barcode_class(
        custom_text,
        writer=ImageWriter()
    )
    barcode_image.write(buffer)
    barcode_base64 = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/png;base64,{barcode_base64}"
