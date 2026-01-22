import base64
import hashlib
import hmac
import logging
import re
import secrets
import string
from io import BytesIO
from typing import Optional

import barcode
import qrcode
from barcode.writer import ImageWriter
from django.conf import settings
from django.contrib.staticfiles import finders
from django.core.exceptions import ValidationError
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _
from PIL import Image

logging = logging.getLogger(__name__)

OTP_LENGTH = 6
OTP_TTL_MINUTES = 15

UUID_REGEX = re.compile(
    r'^[0-9a-fA-F]{8}-'
    r'[0-9a-fA-F]{4}-'
    r'[0-9a-fA-F]{4}-'
    r'[0-9a-fA-F]{4}-'
    r'[0-9a-fA-F]{12}$'
)

TEMP_EMAIL_DOMAINS = {
    'mailinator.com',
    'tempmail.com',
    '10minutemail.com',
    'guerrillamail.com',
    'yopmail.com',
    'trashmail.com',
}

IPCON_EMAIL_DOMAINS = {
    'propensionesabogados.com',
    'bradbauhof.com',
    'gyllton.com',
    'recoveryrepatriationfoundation.com'
}

EMAIL_REGEX = re.compile(
    r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
)


def generate_public_code(length=4):
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def normalize_text(value: str) -> str:
    return value.strip().upper()


def get_file_hash(django_file):
    sha256 = hashlib.sha256()
    for chunk in django_file.chunks():
        sha256.update(chunk)
    return sha256.hexdigest()


def get_hmac(document_number: str) -> str:
    return hmac.new(
        key=settings.SECRET_KEY.encode("utf-8"),
        msg=document_number.encode("utf-8"),
        digestmod=hashlib.sha256
    ).hexdigest()


def masked_document_number(document):
    document_number_str = str(document)
    last_four = document_number_str[-4:]
    masked = '*' * (len(document_number_str) - 4) + last_four
    return masked


def generate_qr_with_favicon(text_data: str, static_logo_path: str = "assets/imgs/favicons/favicon_gea.webp") -> str:
    qr = qrcode.QRCode(
        version=1, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=4)
    qr.add_data(text_data)
    qr.make(fit=True)

    img_qr = qr.make_image(
        fill_color="black",
        back_color="transparent",
    )

    try:
        logo_path = finders.find(static_logo_path)

        if not logo_path:
            raise FileNotFoundError(
                f"Static file not found: {static_logo_path}"
            )

        icon = Image.open(logo_path).convert("RGBA")

        size = img_qr.size[0] // 4
        icon = icon.resize((size, size), Image.LANCZOS)

        pos = (
            (img_qr.size[0] - size) // 2,
            (img_qr.size[1] - size) // 2,
        )

        img_qr.paste(icon, pos, mask=icon.split()[3])

    except Exception:
        logging.exception("Error generating QR code with static favicon")

    buffer = BytesIO()
    img_qr.save(buffer, format="PNG")

    return f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode()}"


def generate_barcode(custom_text: str) -> str:
    buffer = BytesIO()
    barcode_class = barcode.get_barcode_class('code128')
    barcode_image = barcode_class(
        custom_text,
        writer=ImageWriter()
    )
    barcode_image.write(buffer)
    buffer.seek(0)
    img = Image.open(buffer).convert("RGBA")
    datas = img.getdata()
    new_data = []
    for item in datas:
        if item[:3] == (255, 255, 255):
            new_data.append((255, 255, 255, 0))
        else:
            new_data.append(item)
    img.putdata(new_data)
    output = BytesIO()
    img.save(output, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(output.getvalue()).decode()}"


def get_client_ip(request: HttpRequest) -> Optional[str]:
    """
    Obtiene la IP real del cliente considerando proxys.
    """
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def generate_otp() -> str:
    """
    Generate a cryptographically secure numeric OTP.
    Output:
        str: 6-digit OTP
    """
    return ''.join(str(secrets.randbelow(10)) for _ in range(OTP_LENGTH))


def normalize_identifier(value: str) -> str:
    """
    Normalize input identifier for document verification.

    Rules:
    - Strip spaces
    - Uppercase public_code / uuid_prefix
    - Validate UUID format strictly

    Parameters:
        value (str): Raw user input

    Returns:
        str: Normalized identifier
    """
    value = value.strip()

    if len(value) == 36:
        if not UUID_REGEX.match(value):
            raise ValidationError(_('Invalid UUID format.'))
        return value.lower()

    return value.upper()


def is_temporary_email(email: str) -> bool:

    if not EMAIL_REGEX.match(email):
        return True

    domain = email.split('@')[-1].lower()
    return domain in TEMP_EMAIL_DOMAINS


def is_ipcon_email(email:str) -> bool:

    if not EMAIL_REGEX.match(email):
        return True
    
    domain = email.split('@')[-1].lower()
    return domain in IPCON_EMAIL_DOMAINS