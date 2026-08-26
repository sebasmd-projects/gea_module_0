# apps/project/specific/internal/code_gen/views.py

import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import FormView

from .constants import (HASH_B64_DEFAULT_LENGTH, RANDOM_CODE_DEFAULT_LENGTH)
from .forms import (QR_CONTENT_CODE, QR_CONTENT_CUSTOM,
                    QR_CONTENT_VERIFICATION, CodeGeneratorForm)
from .models import CodeRegistrationModel
from .services.certification import (CertificationError, CodeOptions,
                                     build_verification_url)
from .services.certification import certify_document as run_certification
from .services.codes import (barcode_length_warning, build_code_payload,
                             derive_initials, generate_random_code,
                             next_sequence, validate_barcode_payload)
from .services.hashing import hash_to_base64, sha256_hex
from .services.render import png_to_data_uri, render_barcode_png, render_qr_png

logger = logging.getLogger(__name__)


class InternalToolAccessMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    El generador emite codigos institucionales: solo personal interno.
    """

    def test_func(self) -> bool:
        user = self.request.user
        return bool(user.is_active and (user.is_superuser or user.is_staff))


class CodeGeneratorView(InternalToolAccessMixin, FormView):
    """
    Generador de codigos y certificador de documentos.

    Sin archivo, emite el codigo y sus simbolos. Con archivo y la casilla de
    certificacion marcada, ejecuta el flujo completo: estampa el PDF, calcula
    las tres huellas y produce la copia distribuible con marca de agua.
    """

    template_name = 'dashboard/pages/documents/code_gen/code_form.html'
    form_class = CodeGeneratorForm

    def form_valid(self, form):
        data = form.cleaned_data

        try:
            context = self._generate(form, data)
        except (ValidationError, CertificationError) as error:
            messages.error(self.request, self._error_text(error))
            return self.form_invalid(form)
        except Exception:
            logger.exception('Unexpected failure while generating the code')
            messages.error(
                self.request,
                _('The code could not be generated. Check the logs for details.')
            )
            return self.form_invalid(form)

        return self.render_to_response(
            self.get_context_data(form=form, **context)
        )

    @staticmethod
    def _error_text(error) -> str:
        messages_list = getattr(error, 'messages', None)
        if messages_list:
            return ' '.join(str(item) for item in messages_list)
        return str(error)

    # ------------------------------------------------------------------
    # Generacion
    # ------------------------------------------------------------------
    def _generate(self, form, data) -> dict:
        source_file = data.get('source_file')

        source_hash = sha256_hex(source_file) if source_file else ''

        hash_length = data.get('hash_fragment_length') or HASH_B64_DEFAULT_LENGTH
        random_length = data.get('random_code_length') or RANDOM_CODE_DEFAULT_LENGTH

        options = CodeOptions(
            include_nit=data.get('include_nit', False),
            custom_text=data.get('custom_text_input') or '',
            include_initials_sequence=data.get('include_initials_sequence', False),
            initials=(
                data.get('initials')
                or derive_initials(data.get('reference', ''))
            ),
            include_document_hash=bool(
                data.get('include_document_hash') and source_hash
            ),
            hash_fragment_length=hash_length,
            include_date=data.get('include_date', False),
            include_random_code=data.get('include_random_code', False),
            random_code_length=random_length,
        )

        if data.get('certify_document'):
            return self._certify(form, data, options)

        return self._preview(form, data, options, source_hash)

    def _preview(self, form, data, options: CodeOptions, source_hash: str) -> dict:
        """Emite el codigo sin certificar ningun archivo."""
        sequence = next_sequence() if options.include_initials_sequence else ''
        random_code = (
            generate_random_code(options.random_code_length)
            if options.include_random_code else ''
        )
        hash_fragment = (
            hash_to_base64(source_hash, options.hash_fragment_length)
            if options.include_document_hash else ''
        )

        code_payload = build_code_payload(
            include_nit=options.include_nit,
            custom_text=options.custom_text,
            initials=options.initials if options.include_initials_sequence else '',
            sequence=sequence,
            hash_fragment=hash_fragment,
            issue_date=timezone.localdate() if options.include_date else None,
            random_code=random_code,
        )

        if not code_payload:
            raise ValidationError(
                _('Select at least one segment to build the code.')
            )

        context = {
            'code_payload': code_payload,
            'source_hash': source_hash,
            'hash_fragment': hash_fragment,
            'sequence': sequence,
            'random_code': random_code,
        }

        if data.get('generate_barcode'):
            self._add_barcode(context, code_payload)

        qr_payload = self._resolve_qr_payload(data, code_payload)

        if qr_payload:
            context['qr_payload'] = qr_payload
            context['qr_image'] = png_to_data_uri(render_qr_png(qr_payload))

        CodeRegistrationModel.objects.create(
            reference=data.get('reference', ''),
            description=data.get('description') or '',
            custom_text_input=data.get('custom_text_input') or '',
            code_information=code_payload,
            initials=options.initials,
            sequence=sequence,
            random_code=random_code,
            source_file_hash=source_hash,
            hash_fragment=hash_fragment,
            generated_barcode=bool(data.get('generate_barcode')),
            generated_qr=bool(qr_payload),
            qr_payload=qr_payload or '',
        )

        return context

    def _certify(self, form, data, options: CodeOptions) -> dict:
        """Crea el documento verificable y ejecuta la certificacion."""
        from apps.project.specific.documents.certificates.models import \
            DocumentVerificationModel

        document = DocumentVerificationModel(
            document_title=data.get('document_title') or data.get('reference'),
            certificate_type=data.get('certificate_type'),
            stamp_layout=data.get('stamp_layout'),
            issued_at=data.get('issued_at') or timezone.localdate(),
            expires_at=data.get('expires_at'),
            code_initials=options.initials,
        )

        document.source_file = data['source_file']
        document.save()

        qr_override = None
        if data.get('qr_content') == QR_CONTENT_CUSTOM:
            qr_override = data.get('qr_custom_value')

        outcome = run_certification(
            document,
            request=self.request,
            options=options,
            qr_payload=qr_override,
        )

        context = {
            'document': document,
            'code_payload': outcome.code_payload,
            'qr_payload': outcome.qr_payload,
            'source_hash': document.source_hash,
            'hash_fragment': document.code_hash_fragment,
            'sequence': document.code_sequence,
            'random_code': document.public_code,
            'stamp_applied': outcome.applied,
            'stamp_skipped': outcome.skipped,
            'page_count': outcome.page_count,
            'verification_url': build_verification_url(document),
        }

        if data.get('generate_barcode'):
            self._add_barcode(context, outcome.code_payload)

        if data.get('generate_qr'):
            context['qr_image'] = png_to_data_uri(
                render_qr_png(outcome.qr_payload)
            )

        messages.success(
            self.request,
            _('Document certified. Public code: %(code)s')
            % {'code': document.public_code}
        )

        return context

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _add_barcode(self, context: dict, code_payload: str) -> None:
        validate_barcode_payload(code_payload)

        warning = barcode_length_warning(code_payload)
        if warning:
            messages.warning(self.request, warning)
            context['barcode_warning'] = warning

        context['barcode_image'] = png_to_data_uri(
            render_barcode_png(code_payload)
        )

    @staticmethod
    def _resolve_qr_payload(data, code_payload: str):
        if not data.get('generate_qr'):
            return None

        qr_content = data.get('qr_content') or QR_CONTENT_VERIFICATION

        if qr_content == QR_CONTENT_CUSTOM:
            return data.get('qr_custom_value')

        if qr_content == QR_CONTENT_CODE:
            return code_payload

        return None
