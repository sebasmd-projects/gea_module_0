# apps/project/specific/documents/certificates/views.py

from django.contrib import messages
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, FormView, TemplateView

from apps.project.specific.internal.code_gen.services.record import (
    document_status, key_id, public_key_b64, record_filename, record_json)

from .constants import FILE_MATCH_SESSION_KEY
from .files import can_access, serve
from .forms import (AnonymousEmailOTPForm, AnonymousOTPVerifyForm,
                    CertificateUserForm, DocumentFileVerificationForm,
                    DocumentVerificationForm)
from .functions import (generate_barcode, generate_otp,
                        generate_qr_with_favicon, get_hmac,
                        normalize_identifier)
from .mixins import OTPProtectedDocumentMixin, OTPSessionMixin
from .models import (DocumentCopyKind, DocumentTypeChoices,
                     DocumentVerificationModel, UserCertificateTypeChoices,
                     UserVerificationModel)
from .utils import send_otp_email, track_certificate_view, track_document_view
from .verification import find_document_by_identifier, identify_uploaded_document
from django.urls import reverse_lazy


class InputEmployeeIPCONFormView(FormView):
    template_name = 'dashboard/pages/certificates/users/employee_ipcon/certificate_input.html'

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
    template_name = 'dashboard/pages/certificates/users/employee_ipcon/certificate_detail.html'

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

    template_name = 'dashboard/pages/certificates/documents/aegis_documents/certificate_input.html'

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

        if not otp_state or otp_state.get("verified"):
            return redirect(self.request.path)

        allowed, remaining = self.can_resend_otp()
        if not allowed:
            messages.warning(
                self.request,
                _("Please wait %(seconds)s seconds before requesting a new code.")
                % {"seconds": remaining}
            )
            return redirect(self.request.path)

        email = otp_state.get("email", "")
        allowed_send, _wait = self.can_send_otp(email)
        if not allowed_send:
            messages.warning(self.request, _(
                "Too many code requests. Try again later."))
            return redirect(self.request.path)

        otp = generate_otp()
        self.update_otp(otp)
        send_otp_email(email, otp)

        self.record_send_otp(email)

        messages.success(self.request, _(
            "A new verification code has been sent to your email."))
        return redirect(self.request.path)

    def post(self, request, *args, **kwargs):

        if 'resend_otp' in request.POST:
            return self.resend_otp()

        if 'change_email' in request.POST:
            self.clear_otp_session()
            return redirect(self.request.path)

        if 'verify_by_file' in request.POST and self.file_verification_allowed():
            return self._handle_file_step()

        form = self.get_form()

        if not form.is_valid():
            return self.form_invalid(form)

        if isinstance(form, AnonymousEmailOTPForm):
            return self._handle_email_step(form)

        if isinstance(form, AnonymousOTPVerifyForm):
            return self._handle_otp_step(form)

        return self.form_valid(form)

    def file_verification_allowed(self) -> bool:
        """El cotejo por archivo solo se ofrece tras superar el OTP."""
        if self.request.user.is_authenticated:
            return True

        otp_state = self.get_otp_session()
        return bool(otp_state and otp_state.get('verified'))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if not self.request.user.is_authenticated:
            otp_state = self.get_otp_session()
            if otp_state and not otp_state.get('verified'):
                allowed, remaining = self.can_resend_otp()
                context['otp_resend_remaining'] = remaining

        context['file_verification_allowed'] = self.file_verification_allowed()
        context['file_form'] = kwargs.get(
            'file_form',
            DocumentFileVerificationForm()
        )

        return context

    def _handle_file_step(self):
        """Cotejo del archivo subido contra los documentos certificados."""
        file_form = DocumentFileVerificationForm(
            self.request.POST,
            self.request.FILES
        )

        if not file_form.is_valid():
            return self._render_file_error(file_form)

        match = identify_uploaded_document(
            file_form.cleaned_data['document_file']
        )

        if match is None:
            file_form.add_error(
                'document_file',
                _(
                    'This file is not valid: it is neither the original nor a '
                    'certified digital copy issued by this platform.'
                )
            )
            return self._render_file_error(file_form)

        if not match.is_valid:
            file_form.add_error(
                'document_file',
                _(
                    'This file carries the hidden watermark of the platform, so '
                    'it originated from a certified copy, but its content has '
                    'been modified. It is not a valid certified copy.'
                )
            )
            return self._render_file_error(file_form)

        self.request.session[FILE_MATCH_SESSION_KEY] = match.as_session_payload()

        return redirect(
            'certificates:detail_document_verification_aegis',
            pk=match.document.pk
        )

    def _render_file_error(self, file_form):
        """
        Repinta la pagina con el error del archivo.

        El formulario de codigo se devuelve **sin enlazar**: el POST que llega
        aqui es el de la subida y no trae identificador, asi que enlazarlo
        pintaria un "campo obligatorio" espurio en un formulario que el
        usuario ni ha tocado.
        """
        return self.render_to_response(
            self.get_context_data(
                form=self.get_form_class()(),
                file_form=file_form
            )
        )

    def _handle_email_step(self, form):
        email = form.cleaned_data["email"]

        allowed_send, _wait = self.can_send_otp(email)

        if not allowed_send:
            form.add_error("email", _(
                "Too many code requests. Try again later."))
            return self.form_invalid(form)

        otp = generate_otp()
        self.set_otp_session(email, otp, purpose="document_verification")
        send_otp_email(email, otp)

        self.record_send_otp(email)

        return redirect(self.request.path)

    def _handle_otp_step(self, form):
        otp = form.cleaned_data["otp"]

        if not self.is_otp_valid(otp, purpose="document_verification"):
            form.add_error("otp", _("Invalid or expired code."))
            return self.form_invalid(form)

        self.mark_otp_verified()
        return redirect(self.request.path)

    def form_valid(self, form):
        identifier = form.cleaned_data['identifier']
        cert_type = form.cleaned_data['certificate_type']

        document = find_document_by_identifier(identifier, cert_type)

        if document is None:
            if self.request.user.is_authenticated:
                form.add_error("identifier", _("Document not found."))
            else:
                form.add_error("identifier", _(
                    "We could not verify the document with the provided data."))
            return self.form_invalid(form)

        self.request.session.pop(FILE_MATCH_SESSION_KEY, None)

        return redirect(
            'certificates:detail_document_verification_aegis',
            pk=document.pk
        )


class DocumentVerificationDetailView(OTPProtectedDocumentMixin, DetailView):
    model = DocumentVerificationModel

    template_name = 'dashboard/pages/certificates/documents/aegis_documents/certificate_detail.html'

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
            generate_barcode(self.object.code_payload or self.object.public_code)
        )

        context.update(self._file_match_context())
        context.update(self._record_status_context())

        return context

    def _record_status_context(self) -> dict:
        """Estado del certificado, tal y como lo publica el registro."""
        status = document_status(self.object)

        labels = {
            'VALID': _('Valid'),
            'EXPIRED': _('Expired'),
            'REVOKED': _('Revoked'),
            'NOT_CERTIFIED': _('Not certified'),
        }

        classes = {
            'VALID': 'success',
            'EXPIRED': 'warning text-dark',
            'REVOKED': 'danger',
            'NOT_CERTIFIED': 'secondary',
        }

        return {
            'record_status': status,
            'record_status_label': labels.get(status, status),
            'record_status_class': classes.get(status, 'secondary'),
        }

    def _file_match_context(self) -> dict:
        """
        Traduce el resultado del cotejo por archivo guardado en sesion.

        Solo se muestra si corresponde al documento que se esta viendo.
        """
        payload = self.request.session.get(FILE_MATCH_SESSION_KEY)

        if not payload or payload.get('document_id') != str(self.object.pk):
            return {'file_match': None}

        copy_kind = payload.get('copy_kind')
        match_level = payload.get('match_level')

        headlines = {
            DocumentCopyKind.SOURCE: _(
                'Verified file: this is the ORIGINAL document filed with the '
                'platform, unmodified.'
            ),
            DocumentCopyKind.CERTIFIED: _(
                'Verified file: this is the CERTIFIED document, with its codes '
                'embedded, unmodified.'
            ),
            DocumentCopyKind.PUBLIC_COPY: _(
                'Verified file: this is a CERTIFIED DIGITAL COPY of the '
                'original and it is valid.'
            ),
        }

        details = {
            'EXACT': _(
                'Recognised by the exact fingerprint of the file (SHA-256).'
            ),
            'CONTENT': _(
                'The bytes of the file changed (typically document metadata '
                'rewritten while it was emailed or re-saved), but its '
                'renderable content matches the certified one exactly, page by '
                'page.'
            ),
        }

        return {
            'file_match': {
                'copy_kind': copy_kind,
                'match_level': match_level,
                'file_hash': payload.get('file_hash'),
                'headline': headlines.get(copy_kind),
                'detail': details.get(match_level),
                'is_exact': match_level == 'EXACT',
            }
        }


class DocumentFileView(DetailView):
    """
    Unica puerta de salida de los PDF de certificacion.

    Antes colgaban de MEDIA_URL y los servia el servidor web sin pasar por
    aqui, asi que la proteccion OTP del detalle se saltaba con el enlace
    directo. Ahora cada descarga pasa por esta comprobacion.
    """

    model = DocumentVerificationModel

    def get(self, request, *args, **kwargs):
        document = self.get_object()
        kind = self.kwargs.get('kind')

        if not can_access(kind, request.user, self._has_otp_access()):
            # 404 y no 403: un 403 confirmaria que el documento existe.
            raise Http404('not allowed')

        return serve(document, kind)

    def _has_otp_access(self) -> bool:
        """Reutiliza la misma sesion OTP que protege la pagina de detalle."""
        otp_state = self.request.session.get('document_otp')

        if not otp_state or not otp_state.get('verified'):
            return False

        verified_at = otp_state.get('verified_at')

        if not verified_at:
            return False

        try:
            moment = timezone.datetime.fromisoformat(verified_at).astimezone(
                timezone.get_current_timezone()
            )
        except Exception:
            return False

        return timezone.now() - moment <= OTPProtectedDocumentMixin.OTP_ACCESS_TTL


class CertificationRecordView(OTPProtectedDocumentMixin, DetailView):
    """
    Descarga del registro de certificacion en JSON.

    Es el artefacto que se adjunta a un expediente: lleva las tres huellas, la
    fecha, el estado y un sello criptografico, de modo que un auditor puede
    cotejar el archivo que tiene en la mano sin volver a esta plataforma.
    """

    model = DocumentVerificationModel

    def get(self, request, *args, **kwargs):
        document = self.get_object()

        payload = record_json(document, request=request)

        response = HttpResponse(
            payload,
            content_type='application/json; charset=utf-8'
        )
        response['Content-Disposition'] = (
            f'attachment; filename="{record_filename(document)}"'
        )
        return response


def certification_public_key(request):
    """
    Clave publica con la que se verifica el sello del registro.

    Publica y estable: es lo que permite a un tercero comprobar un registro
    sin depender de esta plataforma en el momento de la comprobacion.
    """
    public = public_key_b64()

    if not public:
        return JsonResponse(
            {
                'algorithm': None,
                'public_key': None,
                'detail': _(
                    'This platform is not configured with a public signing '
                    'key. Certification records are sealed with a symmetric '
                    'HMAC that only the platform itself can verify.'
                ),
            },
            json_dumps_params={'indent': 2, 'ensure_ascii': False},
        )

    return JsonResponse(
        {
            'algorithm': 'Ed25519',
            'key_id': key_id(),
            'public_key': public,
            'encoding': 'base64 of the 32-byte raw Ed25519 public key',
            'verifies': _(
                'The "seal.signature" field of a GEA certification record, '
                'over every other field serialised as compact JSON with '
                'sorted keys, UTF-8.'
            ),
        },
        json_dumps_params={'indent': 2, 'ensure_ascii': False},
    )


class CertificatesLandingTemplateView(TemplateView):
    template_name = 'dashboard/pages/certificates/certificates_landing.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["certificates"] = [
            {
                "title": _("AEGIS Documents Certificates"),
                "description": _(
                    "Verify documents protected and issued through the AEGIS certification system."
                ),
                "icon": "bi-shield-lock",
                "icon_color": "text-success",
                "button_class": "btn-outline-success",
                "url": reverse_lazy("certificates:input_document_verification_aegis"),
            },
            {
                "title": _("IPCON Employee Certificate"),
                "description": _(
                    "Validate employment and institutional certificates issued by IPCON."
                ),
                "icon": "bi-building-check",
                "icon_color": "text-success",
                "button_class": "btn-outline-success",
                "url": reverse_lazy("certificates:input_employee_verification_ipcon"),
            },
            # {
            #     "title": _("Propensiones Employee Certificate"),
            #     "description": _(
            #         "Verify employment certificates issued by Propensiones Abogados."
            #     ),
            #     "icon": "bi-briefcase-check",
            #     "icon_color": "text-warning",
            #     "button_class": "btn-outline-warning text-dark",
            #     "url": reverse_lazy("certificates:employee_propensiones_input"),
            # },
            # {
            #     "title": _("Professional Idoneity"),
            #     "description": _(
            #         "Validate professional suitability and idoneity certificates."
            #     ),
            #     "icon": "bi-patch-check",
            #     "icon_color": "text-info",
            #     "button_class": "btn-outline-info",
            #     "url": reverse_lazy("certificates:idoneity_input"),
            # },
        ]

        return context
