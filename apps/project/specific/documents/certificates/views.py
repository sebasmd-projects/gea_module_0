# apps/project/specific/documents/certificates/views.py

from django.contrib import messages
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, FormView, TemplateView

from apps.common.utils.throttling import RateLimit
from apps.project.specific.internal.code_gen.services.record import (
    document_status, key_id, public_key_b64, record_filename, record_json)

from .constants import FILE_MATCH_SESSION_KEY
from .files import can_access, serve, serve_field
from .forms import (AnonymousEmailOTPForm, AnonymousOTPVerifyForm,
                    CertificateUserForm, DocumentFileVerificationForm,
                    DocumentVerificationForm)
from .functions import (generate_barcode, generate_otp,
                        generate_qr_with_favicon, get_hmac,
                        normalize_identifier)
from .mixins import OTPProtectedDocumentMixin, OTPSessionMixin
from .models import (AegisSummaryModel, DocumentCopyKind, DocumentTypeChoices,
                     DocumentVerificationModel, UserCertificateTypeChoices,
                     UserVerificationModel)
from .utils import send_otp_email, track_certificate_view, track_document_view
from .verification import identify_uploaded_document, resolve_identifier
from django.urls import reverse_lazy


class InputEmployeeIPCONFormView(FormView):
    """
    Consulta publica de un certificado de persona.

    Es el formulario **mas expuesto** de la plataforma y el que menos
    protegido estaba: publico, sin OTP, y devolviendo nombre, apellidos y
    fotografia de un empleado a quien acierte un codigo de cuatro caracteres.

    Cuatro caracteres sobre A-Z0-9 son 1.679.616 combinaciones. Sin ningun
    freno eso no es un secreto, es un rato de barrido -- y lo que sale del
    otro lado no son codigos, es la plantilla entera del despacho con sus
    fotos. El mismo formulario acepta ademas numeros de documento, con lo que
    sirve para comprobar si una persona concreta tiene credencial.

    El limite por IP es lo que convierte el barrido en inviable sin estorbar a
    quien verifica una credencial que tiene en la mano.
    """

    template_name = 'dashboard/pages/certificates/users/employee_ipcon/certificate_input.html'

    form_class = CertificateUserForm

    #: Generoso para una persona con una credencial delante, inutil para
    #: recorrer un espacio de un millon y medio.
    throttle = RateLimit('ipcon_lookup', limit=15, window=10 * 60)

    def build_filters(self, document_type, document_number):
        """
        Traduce lo tecleado a un filtro, o devuelve ``None``.

        ``None`` cuando lo escrito no corresponde a **ningun** identificador
        conocido, y eso arregla un fallo aparte: antes, un codigo de longitud
        distinta de 4, 8 o 36 dejaba el filtro con solo el tipo de
        certificado, y el ``.get()`` acababa devolviendo un certificado
        cualquiera --si solo habia uno-- o reventando con
        ``MultipleObjectsReturned``. Una consulta que no identifica a nadie
        tiene que no encontrar nada, no encontrar a alguien.
        """
        filters = {'certificate_type': UserCertificateTypeChoices.EM_IPCON}

        if document_type == DocumentTypeChoices.PA:
            filters['document_number_pa_hash'] = get_hmac(
                document_number.upper())
            return filters

        if document_type == DocumentTypeChoices.CC:
            filters['document_number_cc_hash'] = get_hmac(
                document_number.upper())
            return filters

        if document_type == DocumentTypeChoices.UNIQUE_CODE:
            by_length = {4: 'public_code', 8: 'uuid_prefix', 36: 'public_uuid'}
            field = by_length.get(len(document_number))

            if not field:
                return None

            filters[field] = document_number
            return filters

        return None

    def form_valid(self, form):
        document_number = form.cleaned_data['document_number'].strip()
        document_type = form.cleaned_data['document_type']

        # Se consume el cupo **antes** de buscar, para que acertar y fallar
        # cuesten lo mismo: contando solo los fallos, enumerar sale gratis en
        # cuanto se encuentra el primer codigo valido.
        if not self.throttle.consume(self.request):
            form.add_error(
                'document_number',
                _('Too many verification attempts. Try again later.'),
            )
            return self.form_invalid(form)

        filters = self.build_filters(document_type, document_number)

        certificate = (
            UserVerificationModel.objects.filter(**filters).first()
            if filters else None
        )

        if certificate is None:
            # El mismo mensaje para "no existe" y para "lo que escribiste no
            # es un identificador": distinguirlos le diria al que barre que
            # formato tiene que probar.
            form.add_error('document_number', _('ID Number not found.'))
            return self.form_invalid(form)

        return redirect(
            'certificates:detail_employee_verification_ipcon',
            pk=certificate.id,
        )


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
        if not self.spend_otp_send(email):
            messages.warning(self.request, _(
                "Too many code requests. Try again later."))
            return redirect(self.request.path)

        otp = generate_otp()
        self.update_otp(otp)
        send_otp_email(email, otp)

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

        if not self.spend_otp_send(email):
            form.add_error("email", _(
                "Too many code requests. Try again later."))
            return self.form_invalid(form)

        otp = generate_otp()
        self.set_otp_session(email, otp, purpose="document_verification")
        send_otp_email(email, otp)

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

        # El formulario es un oraculo: dice si un codigo existe, y los codigos
        # son cortos. Sin tope, probarlos todos es cuestion de tiempo de CPU
        # ajeno. El intento se cuenta antes de buscar, para que acertar y
        # fallar cuesten lo mismo.
        if not self.spend_identifier_attempt():
            form.add_error(
                'identifier',
                _('Too many verification attempts. Try again later.')
            )
            return self.form_invalid(form)

        # Un identificador es un identificador: quien lee un codigo impreso no
        # sabe si detras hay un documento o un resumen, y no tiene por que
        # saberlo. Antes solo se miraba la tabla de documentos, asi que el
        # codigo de un resumen --correcto, y en el papel que el usuario tenia
        # delante-- respondia "Document not found".
        kind, found = resolve_identifier(identifier)

        if found is None:
            if self.request.user.is_authenticated:
                form.add_error("identifier", _("Document not found."))
            else:
                form.add_error("identifier", _(
                    "We could not verify the document with the provided data."))
            return self.form_invalid(form)

        self.request.session.pop(FILE_MATCH_SESSION_KEY, None)

        if kind == 'summary':
            return redirect('certificates:summary_detail', pk=found.pk)

        return redirect(
            'certificates:detail_document_verification_aegis',
            pk=found.pk
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


class EmployeePhotoView(DetailView):
    """
    Foto del empleado de un certificado IPCON.

    La pagina de detalle que la muestra es publica, asi que esta vista tambien
    lo es: seria absurdo proteger la imagen mas que la pagina donde aparece.
    Lo que gana pasando por Django es que deja de colgar de un directorio
    enumerable junto a los PDF de certificacion, que si son sensibles.
    """

    model = UserVerificationModel

    def get(self, request, *args, **kwargs):
        certificate = self.get_object()

        return serve_field(
            certificate.employee_photo,
            filename=f'foto-{certificate.uuid_prefix or certificate.pk}.jpg',
            inline=True,
        )


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


class AegisSummaryDetailView(OTPProtectedDocumentMixin, DetailView):
    """
    Pagina publica del resumen: sus miembros y su estado de anclaje.
    """

    model = AegisSummaryModel
    template_name = 'dashboard/pages/certificates/documents/aegis_documents/summary_detail.html'
    context_object_name = 'summary'

    def get_context_data(self, **kwargs):
        from apps.project.specific.internal.code_gen.services.anchoring import (
            anchor_url, summary_anchor_state)

        context = super().get_context_data(**kwargs)
        context['state'] = summary_anchor_state(self.object)
        context['anchor_url'] = anchor_url(self.object)
        context['members'] = self.object.ordered_members()
        return context


class AegisSummaryAnchorView(DetailView):
    """
    Destino del QR del anclaje.

    **Publica y sin OTP a proposito**: es la pagina que abre quien escanea el
    codigo impreso, y solo muestra hashes y fechas, nada del contenido de los
    documentos. Pedir un OTP aqui convertiria el QR en un callejon.

    Es tambien la razon de que el QR apunte aqui y no lleve la prueba dentro:
    esta pagina se actualiza sola segun maduran los anclajes, sin reestampar
    el PDF.
    """

    model = AegisSummaryModel
    template_name = 'dashboard/pages/certificates/documents/aegis_documents/summary_anchor.html'
    context_object_name = 'summary'

    def get_context_data(self, **kwargs):
        from apps.project.specific.internal.code_gen.services.anchoring import             summary_anchor_state

        context = super().get_context_data(**kwargs)
        context['state'] = summary_anchor_state(self.object)
        context['members'] = self.object.ordered_members()
        return context


def summary_master_payload(request, pk):
    """
    Los bytes exactos sobre los que se calculo el master hash.

    Se sirven verbatim para que un auditor pueda recalcular el SHA-256 por su
    cuenta y comprobar que da la cifra anclada.
    """
    summary = get_object_or_404(AegisSummaryModel, pk=pk)

    if not summary.canonical_payload:
        raise Http404('not sealed')

    response = HttpResponse(
        summary.canonical_payload,
        content_type='application/json; charset=utf-8'
    )
    response['Content-Disposition'] = (
        f'attachment; filename="master-payload-'
        f'{summary.public_code or summary.uuid_prefix}.json"'
    )
    return response


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
