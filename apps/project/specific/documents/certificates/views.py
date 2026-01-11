from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, FormView

from .forms import (AnonymousEmailOTPForm, AnonymousOTPVerifyForm,
                    CertificateUserForm, DocumentVerificationForm)
from .functions import (generate_barcode, generate_otp,
                        generate_qr_with_favicon, get_hmac,
                        normalize_identifier)
from .mixins import OTPProtectedDocumentMixin, OTPSessionMixin
from .models import (DocumentTypeChoices, DocumentVerificationModel,
                     UserCertificateTypeChoices, UserVerificationModel)
from .utils import send_otp_email, track_certificate_view, track_document_view


class InputEmployeeIPCONFormView(FormView):
    template_name = 'dashboard/pages/documents/certificates/employee_ipcon/certificate_input.html'
    form_class = CertificateUserForm

    def form_valid(self, form):
        document_type = form.cleaned_data['document_type']
        document_number = form.cleaned_data['document_number'].strip()
        certificate_type = UserCertificateTypeChoices.EM_IPCON

        if document_type in [DocumentTypeChoices.PA, DocumentTypeChoices.CC]:
            document = get_hmac(document_number.upper())

        filters = {
            'certificate_type': certificate_type,
        }

        if document_type == DocumentTypeChoices.PA:
            filters['document_number_pa_hash'] = document
        elif document_type == DocumentTypeChoices.CC:
            filters['document_number_cc_hash'] = document

        if len(document_number) == 4 and document_type == DocumentTypeChoices.UNIQUE_CODE:
            filters['public_code'] = document_number
        elif len(document_number) == 8 and document_type == DocumentTypeChoices.UNIQUE_CODE:
            filters['uuid_prefix'] = document_number
        elif len(document_number) == 36 and document_type == DocumentTypeChoices.UNIQUE_CODE:
            filters['public_uuid'] = document_number

        try:
            certificate = UserVerificationModel.objects.get(
                **filters
            )
            return redirect(
                'certificates:detail_employee_verification_ipcon',
                pk=certificate.id
            )

        except UserVerificationModel.DoesNotExist:
            form.add_error('document_number', _('ID Number not found.'))
            return self.form_invalid(form)


class EmployeeIPCONDetailView(DetailView):
    model = UserVerificationModel
    template_name = 'dashboard/pages/documents/certificates/employee_ipcon/certificate_detail.html'
    context_object_name = 'certificate'

    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)

        track_certificate_view(
            request=request,
            certificate_user=self.object,
        )

        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        relative_url = reverse(
            'certificates:detail_employee_verification_ipcon',
            kwargs={'pk': self.object.pk}
        )
        absolute_url = self.request.build_absolute_uri(relative_url)
        context['qr_code'] = mark_safe(
            generate_qr_with_favicon(absolute_url)
        )
        context['barcode'] = mark_safe(
            generate_barcode(absolute_url)
        )
        return context


class InputDocumentVerificationFormView(OTPSessionMixin, FormView):

    template_name = 'dashboard/pages/documents/certificates/aegis_documents/certificate_input.html'
    form_class = DocumentVerificationForm

    def get_form_class(self):
        request = self.request

        # === AUTENTICADO ===
        if request.user.is_authenticated:
            return DocumentVerificationForm

        otp_state = self.get_otp_session()

        if not otp_state:
            return AnonymousEmailOTPForm

        if not otp_state.get('verified'):
            return AnonymousOTPVerifyForm

        return DocumentVerificationForm

    def resend_otp(self):
        otp_state = self.get_otp_session()

        if not otp_state or otp_state.get('verified'):
            return redirect(self.request.path)

        allowed, remaining = self.can_resend_otp()

        if not allowed:
            messages.warning(
                self.request,
                _('Please wait %(seconds)s seconds before requesting a new code.')
                % {'seconds': remaining}
            )
            return redirect(self.request.path)

        otp = generate_otp()
        self.update_otp(otp)
        send_otp_email(otp_state['email'], otp)

        messages.success(
            self.request,
            _('A new verification code has been sent to your email.')
        )

        return redirect(self.request.path)

    def post(self, request, *args, **kwargs):

        if 'resend_otp' in request.POST:
            return self.resend_otp()

        if 'change_email' in request.POST:
            self.clear_otp_session()
            return redirect(self.request.path)

        form = self.get_form()

        if not form.is_valid():
            return self.form_invalid(form)

        if isinstance(form, AnonymousEmailOTPForm):
            return self._handle_email_step(form)

        if isinstance(form, AnonymousOTPVerifyForm):
            return self._handle_otp_step(form)

        return self.form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if not self.request.user.is_authenticated:
            otp_state = self.get_otp_session()
            if otp_state and not otp_state.get('verified'):
                allowed, remaining = self.can_resend_otp()
                context['otp_resend_remaining'] = remaining

        return context

    
    def _handle_email_step(self, form):
        if not form.is_valid():
            return self.form_invalid(form)

        email = form.cleaned_data['email']
        otp = generate_otp()

        self.set_otp_session(email, otp)
        send_otp_email(email, otp)

        return redirect(self.request.path)

    def _handle_otp_step(self, form):
        if not form.is_valid():
            return self.form_invalid(form)

        if not self.is_otp_valid(form.cleaned_data['otp']):
            form.add_error('otp', _('Invalid or expired code.'))
            return self.form_invalid(form)

        self.mark_otp_verified()
        return redirect(self.request.path)

    def form_valid(self, form):
        identifier = normalize_identifier(form.cleaned_data['identifier'])
        cert_type = form.cleaned_data['certificate_type']

        filters = {'certificate_type': cert_type}

        if len(identifier) == 4:
            filters['public_code'] = identifier
        elif len(identifier) == 8:
            filters['uuid_prefix'] = identifier
        else:
            filters['id'] = identifier

        try:
            document = DocumentVerificationModel.objects.get(**filters)
        except DocumentVerificationModel.DoesNotExist:
            form.add_error('identifier', _('Document not found.'))
            return self.form_invalid(form)

        return redirect(
            'certificates:detail_document_verification_aegis',
            pk=document.pk
        )


class DocumentVerificationDetailView(OTPProtectedDocumentMixin, DetailView):
    model = DocumentVerificationModel
    template_name = 'dashboard/pages/documents/certificates/aegis_documents/certificate_detail.html'
    context_object_name = 'document'

    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)

        anonymous_email = None
        otp_state = request.session.get('document_otp')
        if otp_state and otp_state.get('verified'):
            anonymous_email = otp_state['email']

        track_document_view(
            request=request,
            document_verification=self.object,
            user=request.user if request.user.is_authenticated else None,
            anonymous_email=anonymous_email,
            deduplicate_minutes=1
        )

        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        relative_url = reverse(
            'certificates:detail_document_verification_aegis',
            kwargs={'pk': self.object.pk}
        )

        absolute_url = self.request.build_absolute_uri(relative_url)

        context['qr_code'] = mark_safe(
            generate_qr_with_favicon(absolute_url)
        )

        context['barcode'] = mark_safe(
            generate_barcode(absolute_url)
        )
        return context
