# apps/project/specific/internal/code_gen/views.py

import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import urlencode
from django.utils.translation import gettext_lazy as _
from django.views.generic import (CreateView, DetailView, FormView,
                                  ListView, TemplateView)

from .preview import placements_as_data, render_preview_container

from .constants import (HASH_B64_DEFAULT_LENGTH, RANDOM_CODE_DEFAULT_LENGTH)
from .forms import (QR_CONTENT_CODE, QR_CONTENT_CUSTOM,
                    QR_CONTENT_VERIFICATION, CodeGeneratorForm)
from .forms import (AegisSummaryForm, StampLayoutForm,
                    StampPlacementFormSet)
from .models import (AnchorChoices, CodeKindChoices, CodeRegistrationModel,
                     PageSelectorChoices, StampLayoutModel,
                     StampPlacementModel)
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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Opciones para las filas que el banco de trabajo crea en cliente.
        context['kind_choices'] = CodeKindChoices.choices
        context['page_selector_choices'] = PageSelectorChoices.choices
        context['anchor_choices'] = AnchorChoices.choices

        return context

    def form_valid(self, form):
        data = form.cleaned_data

        try:
            registration = self._generate(form, data)
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

        # Redireccion tras POST: el resultado vive en una URL permanente, de
        # modo que se puede volver a el, compartirlo o recargar la pagina sin
        # emitir un codigo nuevo ni volver a certificar.
        return redirect('code_gen:code_detail', pk=registration.pk)

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

        return self._issue_code(form, data, options, source_hash)

    def _issue_code(self, form, data, options: CodeOptions, source_hash: str):
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

        if data.get('generate_barcode'):
            # Se valida ahora para fallar antes de guardar nada.
            validate_barcode_payload(code_payload)

            warning = barcode_length_warning(code_payload)
            if warning:
                messages.warning(self.request, warning)

        qr_payload = self._resolve_qr_payload(data, code_payload)

        return CodeRegistrationModel.objects.create(
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

        warning = barcode_length_warning(outcome.code_payload)
        if warning:
            messages.warning(self.request, warning)

        if outcome.skipped:
            messages.warning(
                self.request,
                _('Some placements did not match any page: %(items)s')
                % {'items': ', '.join(outcome.skipped)}
            )

        messages.success(
            self.request,
            _('Document certified. Public code: %(code)s')
            % {'code': document.public_code}
        )

        return outcome.registration

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
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


# ======================================================================
# Historial: el resultado de una generacion vive en una URL permanente
# ======================================================================

class CodeHistoryListView(InternalToolAccessMixin, ListView):
    """
    Todos los codigos emitidos, para poder volver a cualquiera.

    Cada certificacion registra tambien su codigo, asi que este listado cubre
    igualmente los documentos certificados.
    """

    model = CodeRegistrationModel
    template_name = 'dashboard/pages/documents/code_gen/code_history.html'
    context_object_name = 'registrations'
    paginate_by = 25

    def get_queryset(self):
        queryset = (
            CodeRegistrationModel.objects
            .select_related('document')
            .order_by('-created')
        )

        search = (self.request.GET.get('q') or '').strip()

        if search:
            queryset = queryset.filter(
                Q(reference__icontains=search)
                | Q(code_information__icontains=search)
                | Q(sequence__icontains=search)
                | Q(random_code__icontains=search)
                | Q(source_file_hash__icontains=search)
                | Q(document__document_title__icontains=search)
            )

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search'] = self.request.GET.get('q', '')
        return context


class CodeDetailView(InternalToolAccessMixin, DetailView):
    """
    Resultado de una generacion, reconstruido a partir de lo almacenado.

    Los simbolos no se guardan como archivos: se vuelven a renderizar desde el
    payload, de modo que son siempre coherentes con el codigo registrado.
    """

    model = CodeRegistrationModel
    template_name = 'dashboard/pages/documents/code_gen/code_detail.html'
    context_object_name = 'registration'

    def get_queryset(self):
        return CodeRegistrationModel.objects.select_related('document')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        registration = self.object

        if registration.has_barcode:
            try:
                context['barcode_image'] = png_to_data_uri(
                    render_barcode_png(registration.code_information)
                )
                context['barcode_warning'] = barcode_length_warning(
                    registration.code_information
                )
            except Exception:
                logger.exception('Could not re-render the barcode')

        if registration.generated_qr and registration.qr_payload:
            try:
                context['qr_image'] = png_to_data_uri(
                    render_qr_png(registration.qr_payload)
                )
            except Exception:
                logger.exception('Could not re-render the QR code')

        document = registration.document

        if document is not None:
            context['document'] = document
            context['verification_url'] = build_verification_url(document)
            context['record_url'] = reverse(
                'certificates:certification_record',
                kwargs={'pk': document.pk}
            )
            context['layout_placements'] = placements_as_data(
                document.stamp_layout
            )
            context['stamp_preview'] = render_preview_container(
                placements=placements_as_data(document.stamp_layout),
                editable=False,
            )

        return context


# ======================================================================
# Disposiciones de estampado en el dashboard
# ======================================================================

class StampLayoutListView(InternalToolAccessMixin, ListView):
    model = StampLayoutModel
    template_name = 'dashboard/pages/documents/code_gen/layout_list.html'
    context_object_name = 'layouts'
    paginate_by = 25

    def get_queryset(self):
        return (
            StampLayoutModel.objects
            .prefetch_related('placements')
            .order_by('-is_default', 'name')
        )


class StampLayoutEditView(InternalToolAccessMixin, TemplateView):
    """
    Editor de una disposicion con vista previa en vivo.

    El formset y la vista previa comparten los mismos inputs: el JS lee las
    filas y repinta al vuelo, y al arrastrar una caja escribe de vuelta los
    desplazamientos.
    """

    template_name = 'dashboard/pages/documents/code_gen/layout_form.html'

    def get_layout(self):
        pk = self.kwargs.get('pk')

        if pk is None:
            return None

        return get_object_or_404(StampLayoutModel, pk=pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        layout = kwargs.get('layout', self.get_layout())

        context['layout'] = layout
        context['form'] = kwargs.get('form') or StampLayoutForm(instance=layout)
        context['formset'] = kwargs.get('formset') or StampPlacementFormSet(
            instance=layout
        )
        context['stamp_preview'] = render_preview_container(
            row_selector='[data-placement-row]',
            form_scope='#layoutForm',
            editable=True,
        )
        return context

    def post(self, request, *args, **kwargs):
        layout = self.get_layout()

        form = StampLayoutForm(request.POST, instance=layout)
        formset = StampPlacementFormSet(request.POST, instance=layout)

        if not form.is_valid():
            return self.render_to_response(
                self.get_context_data(
                    layout=layout, form=form, formset=formset
                )
            )

        layout = form.save()

        formset = StampPlacementFormSet(request.POST, instance=layout)

        if not formset.is_valid():
            return self.render_to_response(
                self.get_context_data(
                    layout=layout, form=form, formset=formset
                )
            )

        formset.save()

        messages.success(request, _('Stamp layout saved.'))

        return redirect('code_gen:layout_edit', pk=layout.pk)


# ======================================================================
# Compositor del resumen AEGIS
# ======================================================================

class SummaryListView(InternalToolAccessMixin, ListView):
    template_name = 'dashboard/pages/documents/code_gen/summary_list.html'
    context_object_name = 'summaries'
    paginate_by = 25

    def get_queryset(self):
        from apps.project.specific.documents.certificates.models import             AegisSummaryModel

        return (
            AegisSummaryModel.objects
            .prefetch_related('members__document', 'anchors')
            .order_by('-created')
        )


class SummaryCreateView(InternalToolAccessMixin, CreateView):
    """
    Alta de una caja AEGIS sin pasar por el admin.

    Hasta ahora el unico camino era el admin: la lista decia "creala desde el
    admin y componla aqui", que obliga a saltar entre dos interfaces para una
    sola tarea. Aqui se crea y se cae directamente en el compositor, que es lo
    siguiente que hay que hacer.
    """

    form_class = AegisSummaryForm
    template_name = 'dashboard/pages/documents/code_gen/summary_form.html'

    def get_initial(self):
        """
        Preselecciona el activo con el que se vuelve de darlo de alta.

        Se comprueba que exista antes de proponerlo: un UUID inventado en la
        barra de direcciones no debe dejar el formulario en un estado raro.
        """
        initial = super().get_initial()
        asset_id = (self.request.GET.get('asset') or '').strip()

        if not asset_id:
            return initial

        from apps.project.specific.assets_management.assets.models import             AssetModel

        try:
            asset = AssetModel.objects.filter(
                pk=asset_id, is_active=True
            ).first()
        except (ValueError, ValidationError):
            asset = None

        if asset:
            initial['asset'] = asset.pk
            initial['asset_label'] = str(asset)[:200]

        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # El alta de activos tiene su propia pantalla: no se manda a nadie al
        # admin. Se le pasa a donde volver para no perder el hilo.
        context['asset_create_url'] = (
            f"{reverse('assets:create')}?"
            f"{urlencode({'next': self.request.path})}"
        )

        return context

    def form_valid(self, form):
        response = super().form_valid(form)

        messages.success(
            self.request,
            _('Box created. Now add the certificates it contains.')
        )

        return response

    def get_success_url(self):
        return reverse(
            'code_gen:summary_compose', kwargs={'pk': self.object.pk}
        )


class SummaryComposerView(InternalToolAccessMixin, TemplateView):
    """
    Compone la caja: elige los documentos, coloca sus codigos y sella.

    Los codigos de barras de los miembros se arrastran igual que los propios;
    la diferencia es que cada caja sabe de que documento viene.
    """

    template_name = 'dashboard/pages/documents/code_gen/summary_composer.html'

    def get_summary(self):
        from apps.project.specific.documents.certificates.models import             AegisSummaryModel

        return get_object_or_404(AegisSummaryModel, pk=self.kwargs['pk'])

    def get_context_data(self, **kwargs):
        from apps.project.specific.documents.certificates.models import             DocumentVerificationModel
        from apps.project.specific.internal.code_gen.services.anchoring import             anchor_url

        context = super().get_context_data(**kwargs)
        summary = self.get_summary()

        context['summary'] = summary
        context['members'] = summary.ordered_members()
        context['anchor_url'] = anchor_url(summary)
        context['layout'] = (
            summary.summary_document.stamp_layout
            if summary.summary_document else None
        )

        # Candidatos: certificados que todavia no estan en la caja.
        context['candidates'] = (
            DocumentVerificationModel.objects
            .filter(certification_status='CERTIFIED')
            .exclude(pk__in=summary.members.values_list('document_id', flat=True))
            .exclude(pk=summary.summary_document_id or '00000000-0000-0000-0000-000000000000')
            .order_by('-created')[:100]
        )

        context['kind_choices'] = CodeKindChoices.choices
        context['page_selector_choices'] = PageSelectorChoices.choices
        context['anchor_choices'] = AnchorChoices.choices
        context['layouts'] = StampLayoutModel.objects.filter(is_active=True)

        context['stamp_preview'] = render_preview_container(
            row_selector='[data-placement-row]',
            form_scope='#placementTable',
            pdf_input='#summarySourceFile',
            editable=True,
        )

        return context
