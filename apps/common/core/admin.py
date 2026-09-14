"""
Donde se redactan y se aprueban los documentos legales.

Esta es la superficie que hace que el cambio valga la pena: hasta ahora, para
corregir una coma de la politica de datos hacia falta editar una plantilla,
pasar `makemessages`, commitear y desplegar. Quien redacta el documento no es
quien tiene acceso al repositorio.

Tres decisiones que no son de gusto:

- **Aprobar es una accion, no una casilla.** Marcar un desplegable y darle a
  guardar no deja constancia de quien lo hizo; la accion fija aprobador, fecha
  de aprobacion, fecha de vigencia y huella de una vez, y todo eso es
  `editable=False`, asi que no se puede retocar despues desde el formulario.
- **Una version aprobada no se edita**, y el admin no se limita a esconder los
  campos: lo impide `clean()` del modelo, porque esconder no es controlar
  --la misma razon por la que el filtro por entorno de la consola de
  operaciones vive en el registro y no en la plantilla.
- **Las aceptaciones son de solo lectura.** Son la constancia que exige el
  articulo 9 de la Ley 1581; un admin que permitiera editarlas convertiria la
  prueba en una afirmacion.
"""

from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .models import (LegalAcceptanceModel, LegalDocumentModel,
                     LegalDocumentVersionModel, LegalVersionStatus)


class LegalDocumentVersionInline(admin.TabularInline):
    """El historial del documento, que es su traza de cambios."""

    model = LegalDocumentVersionModel
    extra = 0
    can_delete = False
    show_change_link = True

    fields = ('version', 'status', 'effective_from', 'approved_by',
              'approved_at', 'notified_at')
    readonly_fields = fields
    ordering = ('-created',)

    def has_add_permission(self, request, obj=None):
        # Se añade desde el formulario completo de la version, que es donde
        # esta el editor. Aqui solo se lee el historial.
        return False


@admin.register(LegalDocumentModel)
class LegalDocumentAdmin(admin.ModelAdmin):
    list_display = ('es_name', 'key', 'display_current', 'display_draft')
    search_fields = ('es_name', 'en_name', 'key')
    inlines = [LegalDocumentVersionInline]

    @admin.display(description=_('In force'))
    def display_current(self, obj):
        version = obj.current_version()

        if version is None:
            return format_html(
                '<span style="color:#a11a1a">✕ {}</span>',
                _('Nothing approved yet'),
            )

        return format_html(
            '<b>{}</b><br><small>{}</small>',
            version.version,
            version.effective_from.strftime('%d/%m/%Y'),
        )

    @admin.display(description=_('Draft pending'))
    def display_draft(self, obj):
        pending = obj.versions.filter(status=LegalVersionStatus.DRAFT).first()

        if pending is None:
            return '—'

        return format_html('<b>{}</b>', pending.version)


@admin.register(LegalDocumentVersionModel)
class LegalDocumentVersionAdmin(admin.ModelAdmin):
    list_display = ('document', 'version', 'display_status', 'effective_from',
                    'approved_by', 'display_acceptances', 'notified_at')
    list_filter = ('status', 'document', 'notify_users')
    search_fields = ('version', 'document__es_name', 'content_hash')
    date_hierarchy = 'created'
    ordering = ('-created',)

    fieldsets = (
        (None, {
            'fields': ('document', 'version', 'notify_users'),
        }),
        (_('Text'), {
            'fields': ('es_body', 'en_body'),
            'description': _(
                'Spanish is the wording that governs: these documents are '
                'Colombian. English is a courtesy translation.'
            ),
        }),
        (_('What changed'), {
            'fields': ('change_note_es', 'change_note_en'),
            'description': _(
                'This is what every user receives. Say what changed, not '
                'that something changed.'
            ),
        }),
        (_('Approval'), {
            'fields': ('status', 'effective_from', 'approved_by',
                       'approved_at', 'content_hash'),
            'description': _(
                'Filled in by the approval action. Approving is an act by a '
                'person, with their name on it.'
            ),
        }),
    )

    readonly_fields = ('status', 'approved_by', 'approved_at', 'content_hash')

    actions = ['approve_versions']

    @admin.display(description=_('Status'))
    def display_status(self, obj):
        # El color nunca va solo: lleva su simbolo y su palabra, igual que en
        # el resumen de pruebas (§4-bis.F).
        marcas = {
            LegalVersionStatus.APPROVED: ('#1a7a3c', '✓'),
            LegalVersionStatus.DRAFT: ('#a17f1a', '✎'),
            LegalVersionStatus.RETIRED: ('#6c757d', '—'),
        }
        color, icono = marcas.get(obj.status, ('#6c757d', '·'))

        return format_html(
            '<b style="color:{}">{} {}</b>',
            color, icono, obj.get_status_display(),
        )

    @admin.display(description=_('Accepted by'))
    def display_acceptances(self, obj):
        return obj.acceptances.count()

    def get_readonly_fields(self, request, obj=None):
        campos = list(super().get_readonly_fields(request, obj))

        # Aprobada: el texto ya no se toca. El modelo lo impide igualmente,
        # pero un formulario que te deja escribir y luego rechaza el guardado
        # te hace perder el trabajo.
        if obj is not None and obj.is_approved:
            campos += ['document', 'version', 'es_body', 'en_body',
                       'notify_users', 'effective_from']

        return campos

    def has_delete_permission(self, request, obj=None):
        # Borrar una version aprobada dejaria sus aceptaciones apuntando a
        # nada. La FK es PROTECT, asi que la base tambien se niega; esto
        # evita llegar hasta el error.
        if obj is not None and obj.is_approved:
            return False

        return super().has_delete_permission(request, obj)

    @admin.action(description=_('Approve the selected versions'))
    def approve_versions(self, request, queryset):
        aprobadas, saltadas, incompletas = 0, 0, 0

        for version in queryset:
            if version.is_approved:
                saltadas += 1
                continue

            if not (version.es_body or '').strip():
                incompletas += 1
                continue

            version.approve(user=request.user,
                            effective_from=timezone.localdate())
            aprobadas += 1

        if aprobadas:
            self.message_user(request, _(
                '%(count)s approved, in force from today. Users will be told '
                'on the next run of the notification task — only for the ones '
                'marked to notify.'
            ) % {'count': aprobadas})

        if saltadas:
            self.message_user(request, _(
                '%(count)s were already approved: an approved version is '
                'never re-approved, a new one is created.'
            ) % {'count': saltadas}, level='WARNING')

        if incompletas:
            self.message_user(request, _(
                '%(count)s have no Spanish text. Spanish is the wording that '
                'governs, so it cannot be approved empty.'
            ) % {'count': incompletas}, level='ERROR')


@admin.register(LegalAcceptanceModel)
class LegalAcceptanceAdmin(admin.ModelAdmin):
    """
    La constancia de las autorizaciones. Se consulta, no se edita.

    Es lo que hay que poder enseñar si alguien pregunta --o si lo pregunta la
    Superintendencia-- y una fila que se puede corregir a mano no prueba nada.
    """

    list_display = ('user', 'display_document', 'display_version', 'method',
                    'accepted_at', 'ip_address')
    list_filter = ('method', 'version__document', 'accepted_at')
    search_fields = ('user__username', 'content_hash', 'ip_address')
    date_hierarchy = 'accepted_at'
    ordering = ('-accepted_at',)

    @admin.display(description=_('Document'), ordering='version__document')
    def display_document(self, obj):
        return obj.version.document.es_name

    @admin.display(description=_('Version'))
    def display_version(self, obj):
        # El hash abreviado va al lado a proposito: es lo que convierte la
        # fila en prueba, y no verlo invita a confiar en el numero de version,
        # que es solo una etiqueta.
        return format_html(
            '{}<br><small><code>{}</code></small>',
            obj.version.version, (obj.content_hash or '')[:16],
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
