import base64
import hashlib
import logging
from datetime import timedelta
from io import BytesIO

import barcode
import qrcode
import requests
from barcode.writer import ImageWriter
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, FormView, View
from PIL import Image

from .forms import IDNumberForm, IDNumberMinForm
from .models import CertificateModel, CertificateTypesModel

logging = logging.getLogger(__name__)


def generate_qr_with_favicon(text_data: str, image_url: str = "https://gea.propensionesabogados.com/static/assets/imgs/favicon/gea-favicon512x512.png"):
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


class LockoutTimeView(View):
    def get(self, request):
        lockout_time = request.session.get('lockout_time')
        if lockout_time:
            lockout_time = timezone.make_aware(
                timezone.datetime.fromtimestamp(lockout_time))
            lockout_duration = timedelta(minutes=60)
            if timezone.now() < lockout_time + lockout_duration:
                remaining_time = (
                    lockout_time + lockout_duration - timezone.now()).seconds
                return JsonResponse({'remaining_time': remaining_time})

        return JsonResponse({'remaining_time': 0})


# Idoneity

class CertificateInputView(FormView):
    template_name = 'dashboard/pages/documents/certificates/idoneity/certificate_input.html'
    form_class = IDNumberForm

    def form_valid(self, form):
        max_attempts = 5
        lockout_duration = timedelta(minutes=60)
        failed_attempts = self.request.session.get('failed_attempts', 0)
        lockout_time = self.request.session.get('lockout_time')
        if lockout_time:
            lockout_time = timezone.make_aware(
                timezone.datetime.fromtimestamp(lockout_time))
            if timezone.now() < lockout_time + lockout_duration:
                messages.error(
                    self.request,
                    _('Too many failed attempts.')
                )
                return self.form_invalid(form)
            else:
                self.request.session['failed_attempts'] = 0
                self.request.session['lockout_time'] = None

        document_type = form.cleaned_data['document_type']
        document_number = form.cleaned_data['document_number'].strip().upper()
        document_number_hash = hashlib.sha256(
            document_number.encode()).hexdigest()

        try:
            certificate = CertificateModel.objects.get(
                document_type=document_type,
                document_number_hash=document_number_hash,
                certificate_type=CertificateTypesModel.objects.get(
                    name=CertificateTypesModel.CertificateTypeChoices.IDONEITY
                )
            )
            self.request.session['failed_attempts'] = 0
            self.request.session['lockout_time'] = None
            return redirect('certificates:detail', pk=certificate.id)

        except CertificateModel.DoesNotExist:
            failed_attempts += 1
            self.request.session['failed_attempts'] = failed_attempts
            if failed_attempts >= max_attempts:
                self.request.session['lockout_time'] = timezone.now(
                ).timestamp()
                messages.error(
                    self.request, _(
                        'Too many failed attempts.'
                    )
                )
            else:
                form.add_error('document_number', _('ID Number not found.'))
            return self.form_invalid(form)


class CertificateDetailView(DetailView):
    model = CertificateModel
    template_name = 'dashboard/pages/documents/certificates/idoneity/certificate_detail.html'
    context_object_name = 'certificate'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        custom_text = "gea.propensionesabogados.com/certificate/{}".format(
            str(self.object.pk)
        )

        certificate_url = "https://gea.propensionesabogados.com/certificate/{}".format(
            self.object.pk
        )

        context['qr_code'] = mark_safe(
            generate_qr_with_favicon(certificate_url)
        )

        context['barcode'] = mark_safe(
            generate_barcode(custom_text)
        )

        return context


# Sovereign Purchase

class SovereignPurchaseCertificateInputView(FormView):
    template_name = 'dashboard/pages/documents/certificates/sovereing/certificate_input.html'
    form_class = IDNumberMinForm

    def form_valid(self, form):
        max_attempts = 5
        lockout_duration = timedelta(minutes=60)
        failed_attempts = self.request.session.get('failed_attempts', 0)
        lockout_time = self.request.session.get('lockout_time')
        if lockout_time:
            lockout_time = timezone.make_aware(
                timezone.datetime.fromtimestamp(lockout_time))
            if timezone.now() < lockout_time + lockout_duration:
                messages.error(
                    self.request,
                    _('Too many failed attempts.')
                )
                return self.form_invalid(form)
            else:
                self.request.session['failed_attempts'] = 0
                self.request.session['lockout_time'] = None

        document_type = form.cleaned_data['document_type']
        document_number = form.cleaned_data['document_number'].strip().upper()
        document_number_hash = hashlib.sha256(
            document_number.encode()).hexdigest()

        try:
            certificate = CertificateModel.objects.get(
                document_type=document_type,
                document_number_hash=document_number_hash,
                certificate_type=CertificateTypesModel.objects.get(
                    name=CertificateTypesModel.CertificateTypeChoices.SOVEREIGN_PURCHASE)
            )
            self.request.session['failed_attempts'] = 0
            self.request.session['lockout_time'] = None
            return redirect('certificates:sovereign_detail', pk=certificate.id)

        except CertificateModel.DoesNotExist:
            failed_attempts += 1
            self.request.session['failed_attempts'] = failed_attempts
            if failed_attempts >= max_attempts:
                self.request.session['lockout_time'] = timezone.now(
                ).timestamp()
                messages.error(
                    self.request, _(
                        'Too many failed attempts.'
                    )
                )
            else:
                form.add_error('document_number', _('ID Number not found.'))
            return self.form_invalid(form)


class SovereignPurchaseCertificateDetailView(DetailView):
    model = CertificateModel
    template_name = 'dashboard/pages/documents/certificates/sovereing/certificate_detail.html'
    context_object_name = 'certificate'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        custom_text = "gea.propensionesabogados.com/certificate/sovereing/{}".format(
            str(self.object.pk)
        )

        certificate_url = "https://gea.propensionesabogados.com/certificate/sovereing/{}".format(
            self.object.pk
        )

        context['qr_code'] = mark_safe(
            generate_qr_with_favicon(certificate_url)
        )

        context['barcode'] = mark_safe(
            generate_barcode(custom_text)
        )

        return context
