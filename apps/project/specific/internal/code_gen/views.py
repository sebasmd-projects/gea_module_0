import base64
import logging
import random
import string
from datetime import datetime
from io import BytesIO
from urllib.parse import quote, unquote

import barcode
import qrcode
import requests
import unidecode
from barcode.writer import ImageWriter
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.views.generic import FormView
from PIL import Image

from .forms import CodeForm
from .models import CodeRegistrationModel

logging = logging.getLogger(__name__)

QR_IMG_URL = "https://gea.propensionesabogados.com/static/assets/imgs/favicon/gea-favicon512x512.png"


def generate_random_code(length=4):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))


def generate_barcode(text):
    sanitized_text = unidecode.unidecode(text)
    sanitized_text = ''.join(
        char for char in sanitized_text if char.isalnum() or char.isspace())
    buffer = BytesIO()
    barcode_class = barcode.get_barcode_class('code128')
    barcode_image = barcode_class(sanitized_text, writer=ImageWriter())
    barcode_image.write(buffer)
    buffer.seek(0)
    return buffer


def generate_qr_with_favicon(text_data: str, image_url: str = QR_IMG_URL):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(text_data)
    qr.make(fit=True)
    img_qr = qr.make_image(fill="black", back_color="white").convert("RGB")

    try:
        icon_url = image_url
        response = requests.get(icon_url)
        response.raise_for_status()
        icon = Image.open(BytesIO(response.content))
        icon = icon.resize(
            (img_qr.size[0] // 4, img_qr.size[1] // 4), Image.LANCZOS)
        pos = ((img_qr.size[0] - icon.size[0]) // 2,
               (img_qr.size[1] - icon.size[1]) // 2)
        img_qr.paste(icon, pos, icon)
    except Exception as e:
        logging.error(f"Error: {e}")

    buffer = BytesIO()
    img_qr.save(buffer, format="PNG")
    qr_base64 = base64.b64encode(buffer.getvalue()).decode()

    return f"data:image/png;base64,{qr_base64}"


def dynamic_qr_view(request, text, image_url=QR_IMG_URL):
    """
    Generates a QR code with a favicon dynamically based on the provided text.
    """
    try:
        decoded_text = unquote(text)
        qr_image_data = generate_qr_with_favicon(decoded_text, image_url)
        buffer = BytesIO()
        image_data = base64.b64decode(qr_image_data.split(",")[1])
        buffer.write(image_data)
        buffer.seek(0)
        return HttpResponse(buffer, content_type="image/png")
    except Exception as e:
        logging.error(f"Error generating dynamic QR: {e}")
        return HttpResponse("Error generating QR", status=500)


class CodeGeneratorView(FormView):
    template_name = "dashboard/pages/documents/code_gen/code_form.html"
    form_class = CodeForm

    def form_valid(self, form):
        reference = form.cleaned_data['reference']
        description = form.cleaned_data['description']
        custom_text = form.cleaned_data['custom_text_input'].strip()
        include_nit = form.cleaned_data['include_nit']
        include_date = form.cleaned_data['include_date']
        include_random_code = form.cleaned_data['include_random_code']
        generate_qr_code = form.cleaned_data['generate_qr_code']
        generate_bar_code = form.cleaned_data['generate_barcode']
        include_f991 = form.cleaned_data['include_f991']
        include_m9q0 = form.cleaned_data['include_m9q0']

        # Construir el texto del código
        components = [custom_text]

        if include_nit:
            components.insert(0, '901.409.813-7')

        if include_date:
            components.append(datetime.now().strftime("%d%m%Y"))

        if include_f991:
            components.append('F991')

        if include_m9q0:
            components.append('M9Q0')

        if include_random_code:
            components.append(generate_random_code())

        barcode_text = ' '.join(components).strip()

        response_data = {}

        if generate_bar_code:
            barcode_buffer = generate_barcode(barcode_text)
            barcode_base64 = base64.b64encode(
                barcode_buffer.getvalue()).decode()
            response_data["barcode_image"] = f"data:image/png;base64,{barcode_base64}"

        if generate_qr_code:
            qr_image_url = self.request.build_absolute_uri(
                reverse(
                    "code_gen:dynamic_qr",
                    kwargs={
                        "text": quote(barcode_text),
                    }
                )
            )
            response_data["qr_image_url"] = qr_image_url

        # Guardar en el modelo si no existe
        existing_record = CodeRegistrationModel.objects.filter(
            reference=reference.upper(),
            description=description,
            code_information=barcode_text
        ).first()

        if not existing_record:
            CodeRegistrationModel.objects.create(
                reference=reference.upper(),
                description=description,
                custom_text_input=custom_text,
                code_information=barcode_text
            )

        return JsonResponse(response_data)
