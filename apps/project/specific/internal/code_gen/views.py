# apps/project/specific/internal/code_gen/views.py

import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import urlencode
from django.utils.translation import gettext_lazy as _
from django.views.generic import (CreateView, DetailView, FormView,
                                  ListView, TemplateView, View)

from .access import (can_compose_summaries, can_generate_codes,
                     can_see_internals, can_use_history, can_view_registration,
                     is_operator, visible_registrations)
from .history import annotate_flat, build_history_tree
from .services.usb_bundle import NotReadyToExport, build_bundle
from .services.usb_readiness import export_state
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
        return is_operator(self.request.user)


class HistoryAccessMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    El historial lo abren dos papeles distintos, no uno con menos botones.

    El operador ve todo; el titular ve **sus** certificados y en solo lectura.
    Quien decide que es cada uno es `access.py`, no esta clase: aqui solo se
    deja pasar, y lo que se ve lo recorta el queryset.
    """

    def test_func(self) -> bool:
        return can_use_history(self.request.user)


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
            # Para quien se emite. Vacio es valido: hay certificados que no son
            # de nadie en particular. Puesto, es lo unico que le deja ver este
            # certificado en su historial (`access.visible_registrations`).
            holder=data.get('holder'),
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

class CodeHistoryListView(HistoryAccessMixin, ListView):
    """
    Todos los codigos emitidos, en dos modos que no dicen lo mismo.

    Cada certificacion registra tambien su codigo, asi que este listado cubre
    igualmente los documentos certificados.

    - **Arbol** (por defecto): cada resumen con los suyos debajo. Lo que se
      pagina son **ramas, no filas** — un resumen entra entero o no entra:
      partirlo por el corte lo dejaria repetido arriba en dos paginas con
      miembros distintos, y un arbol a medias se lee como completo.
    - **Lista**: una fila por codigo, sin repetir ninguno, diciendo de que
      resumenes es cada uno. Aqui no hay ramas que partir, asi que la
      paginacion vuelve a ser la de la base de datos.

    Existen los dos porque un certificado puede estar en varios resumenes, y
    entonces «cuantas filas hay» y «cuantos codigos se han emitido» dejan de
    ser el mismo numero. El porque, en `history.py`.
    """

    model = CodeRegistrationModel
    template_name = 'dashboard/pages/documents/code_gen/code_history.html'
    paginate_by = 25

    #: Valor de `?view=` que pide la lista. Cualquier otra cosa es el arbol,
    #: que es el modo por defecto: una URL vieja o manipulada cae en el, no en
    #: un error.
    FLAT = 'flat'

    @property
    def grouped(self) -> bool:
        return self.request.GET.get('view') != self.FLAT

    def get_registrations(self):
        queryset = (
            CodeRegistrationModel.objects
            .select_related('document')
            .order_by('-created')
        )

        # Antes de buscar y antes de agrupar. Recortar despues dejaria que la
        # busqueda contestara sobre filas que esta persona no puede ver --el
        # numero de resultados ya dice si existe algo con ese texto-- y que el
        # arbol se armara con ramas que luego habria que quitar.
        queryset = visible_registrations(queryset, self.request.user)

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

    def get_queryset(self):
        queryset = self.get_registrations()

        if not self.grouped:
            # En lista no hay nada que agrupar, asi que se devuelve el
            # QuerySet tal cual y pagina la base de datos: veinticinco filas
            # por peticion, como toda la vida.
            return queryset

        registrations = list(queryset)

        # La cifra que importa sigue siendo la de codigos: el numero de ramas
        # no dice cuantos se han emitido, y es lo que se viene a mirar. Se
        # guarda aqui porque contar las filas del arbol daria de mas --un
        # certificado que este en dos resumenes sale en los dos.
        self.code_count = len(registrations)

        return build_history_tree(registrations)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search'] = self.request.GET.get('q', '')
        context['grouped'] = self.grouped
        context['flat_value'] = self.FLAT

        # Lo que la plantilla puede enseñar. Sale de `access.py` y no de
        # `user.is_staff` escrito en la plantilla: con la regla en un solo
        # sitio, cambiarla no obliga a acordarse de siete plantillas.
        usuario = self.request.user
        context['is_operator'] = is_operator(usuario)
        context['can_compose'] = can_compose_summaries(usuario)
        context['can_generate'] = can_generate_codes(usuario)

        if self.grouped:
            nodes = context['object_list']

            # Solo las ramas de esta pagina, y solo para quien puede exportar.
            # Comprobar si un resumen se puede llevar en un USB obliga a rehacer
            # su master hash y a leer sus pruebas de anclaje; hacerlo sobre el
            # historial entero para enseñar una pagina seria pagar por lo que no
            # se ve, y hacerlo para un titular seria pagarlo por lo que ademas
            # no se le enseña. Todo es local: leer un `.ots` es parsearlo, no
            # consultar la cadena.
            if context['can_compose']:
                for node in nodes:
                    if node.is_summary:
                        node.export = export_state(node.summary)

            context['nodes'] = nodes
            context['code_count'] = getattr(self, 'code_count', 0)
        else:
            # Sobre la pagina ya cortada: dos consultas para veinticinco
            # filas, no para el historial entero.
            context['rows'] = annotate_flat(context['object_list'])
            context['code_count'] = context['paginator'].count

        return context


class SummaryUSBExportView(InternalToolAccessMixin, View):
    """
    El dossier de un resumen, empaquetado para grabarlo en un USB.

    **Solo si esta todo en verde.** Un USB sale de aqui y no vuelve: no se
    actualiza, no avisa y no se puede retirar. Exportar un resumen a medias
    --sellado pero sin confirmar en la cadena, o con un anclaje que ya no cubre
    el master hash de ahora-- reparte un dossier que parece prueba y no lo es,
    y quien lo recibe no tiene forma de notarlo. Las cinco condiciones y el
    porque estan en `services/usb_readiness.py`.

    Se arma en memoria y se devuelve: no se guarda en disco. Un archivo
    guardado obligaria a decidir su carpeta en `deploy/media.htaccess`
    (invariante 13) y a regenerarlo cada vez que cambie algo del resumen.
    """

    def get(self, request, *args, **kwargs):
        # Import dentro de la funcion: `certificates` y `code_gen` se importan
        # mutuamente a proposito (CLAUDE.md §4-bis.B) y en el encabezado seria
        # circular.
        from apps.project.specific.documents.certificates.models import \
            AegisSummaryModel

        summary = get_object_or_404(
            AegisSummaryModel, pk=kwargs['pk'], is_active=True)

        try:
            nombre, contenido = build_bundle(summary, requested_by=request.user)
        except NotReadyToExport as falta:
            # La pagina ya pinta la lista de las cinco, asi que aqui solo se
            # llega escribiendo la URL o si el estado cambio entre que se
            # dibujo el boton y se pulso. Un aviso, no cinco: lo que hace falta
            # es que quede claro por que no bajo el archivo.
            pendientes = [
                f'{check.label}: {check.detail}' if check.detail
                else str(check.label)
                for check in falta.checks
                if not check.ok
            ]

            messages.error(
                request,
                _('This summary cannot be exported yet. %(reasons)s')
                % {'reasons': ' '.join(pendientes)},
            )

            # Al compositor, que es donde se sella, se emite y se manda a
            # anclar: es lo que hay que hacer para ponerlo en verde.
            return redirect('code_gen:summary_compose', pk=summary.pk)

        respuesta = HttpResponse(
            contenido, content_type='application/zip')
        respuesta['Content-Disposition'] = f'attachment; filename="{nombre}"'

        logger.info(
            'Dossier USB generado: resumen=%s por=%s (%s bytes)',
            summary.pk, request.user.pk, len(contenido),
        )

        return respuesta


class CodeDetailView(HistoryAccessMixin, DetailView):
    """
    Resultado de una generacion, reconstruido a partir de lo almacenado.

    Los simbolos no se guardan como archivos: se vuelven a renderizar desde el
    payload, de modo que son siempre coherentes con el codigo registrado.
    """

    model = CodeRegistrationModel
    template_name = 'dashboard/pages/documents/code_gen/code_detail.html'
    context_object_name = 'registration'

    def get_queryset(self):
        """
        Recortado en la base de datos, no en la plantilla.

        Un titular que teclee el id de un codigo que no es suyo se lleva un
        **404**, que es lo mismo que le contesta una ruta que no existe. Un 403
        le confirmaria que ese codigo existe, que es justo lo que no tiene que
        poder averiguar (invariantes 7 y 20).
        """
        queryset = CodeRegistrationModel.objects.select_related(
            'document', 'document__holder')

        return visible_registrations(queryset, self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        registration = self.object

        # Las piezas de trabajo: los simbolos sueltos, el original y la
        # geometria del estampado. Aqui no se decide esconderlas: **no se
        # producen**. Renderizar un QR para no enseñarlo lo deja en la memoria
        # del proceso y a una linea de plantilla de distancia de salir.
        internals = can_see_internals(self.request.user)
        context['can_see_internals'] = internals

        if internals and registration.has_barcode:
            try:
                context['barcode_image'] = png_to_data_uri(
                    render_barcode_png(registration.code_information)
                )
                context['barcode_warning'] = barcode_length_warning(
                    registration.code_information
                )
            except Exception:
                logger.exception('Could not re-render the barcode')

        if internals and registration.generated_qr and registration.qr_payload:
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

        if document is not None and internals:
            context['layout_placements'] = placements_as_data(
                document.stamp_layout
            )
            # Este documento ya existe, asi que la vista previa dibuja lo que
            # lleva de verdad y no una muestra: el ancho de un Code128 depende
            # de la longitud del codigo, y con una muestra corta parece caber
            # lo que en el papel se sale.
            context['stamp_preview'] = render_preview_container(
                placements=placements_as_data(document.stamp_layout),
                editable=False,
                barcode_payload=document.code_payload or '',
                qr_payload=(
                    document.qr_payload or context['verification_url'] or ''
                ),
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
    filas y repinta al vuelo, y al arrastrar un resumen escribe de vuelta los
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
    Alta de un resumen AEGIS sin pasar por el admin.

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
            _('Summary created. Now add the certificates it gathers.')
        )

        return response

    def get_success_url(self):
        return reverse(
            'code_gen:summary_compose', kwargs={'pk': self.object.pk}
        )


class SummaryComposerView(InternalToolAccessMixin, TemplateView):
    """
    Compone el resumen: elige los documentos, coloca sus codigos y sella.

    Los codigos de barras de los miembros se arrastran igual que los propios;
    la diferencia es que cada resumen sabe de que documento viene.
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

        # Estado del envio a la cadena de bloques al pintar la pagina. Despues
        # lo mantiene al dia el JS con lo que devuelve cada sellado o envio.
        from .api import _ots_anchor_for_current_hash

        sent = _ots_anchor_for_current_hash(summary)

        context['sent_to_blockchain'] = sent is not None
        context['blockchain_label'] = (
            sent.get_status_display() if sent is not None else _('Not sent')
        )
        context['can_send_to_blockchain'] = (
            bool(summary.master_hash) and sent is None
        )
        context['layout'] = (
            summary.summary_document.stamp_layout
            if summary.summary_document else None
        )

        # Candidatos: certificados que todavia no estan en el resumen.
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

        # Los enlaces al documento los pinta el servidor. Antes salian con
        # href="#" y solo el JS los rellenaba, y solo despues de emitir: al
        # entrar en un resumen ya emitido los tres llevaban a la misma pagina.
        from .api import _summary_document_payload

        context['document'] = _summary_document_payload(summary)

        context['stamp_preview'] = render_preview_container(
            row_selector='[data-placement-row]',
            form_scope='#placementTable',
            pdf_input='#summarySourceFile',
            editable=True,
            **self.real_symbols(summary),
        )

        return context

    def real_symbols(self, summary) -> dict:
        """
        Lo que de verdad se va a estampar, para que la vista previa no mienta.

        Con simbolos de muestra la vista previa engana justo en lo que se
        mira: el ancho de un Code128 depende de cuantos caracteres lleve, asi
        que una muestra corta cabe donde el codigo real no cabria. Con el
        resumen ya compuesto no hay que adivinar nada, porque los cuatro
        contenidos existen.
        """
        from .services.anchoring import anchor_url, summary_verification_url
        from .services.summary import master_barcode_payload

        payloads = {'members': {}}

        if summary.master_hash:
            payloads['barcode_payload'] = master_barcode_payload(summary)

        payloads['qr_payload'] = summary_verification_url(summary)
        payloads['anchor_payload'] = anchor_url(summary)

        for member in summary.ordered_members():
            code = (member.document.code_payload or '').strip()

            if code:
                payloads['members'][member.code] = code

        return payloads
