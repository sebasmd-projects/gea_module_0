# apps/project/common/pqrs/admin.py
"""
El panel de tramite de las PQRS.

Lo que decide si esto sirve o no es una cosa: **que se vea de un vistazo lo
que esta a punto de vencer**. Un listado ordenado por fecha de radicacion no
sirve para eso, porque una consulta radicada ayer vence antes que un reclamo
de la semana pasada -- los plazos son distintos.

Por eso el orden por defecto es por fecha de vencimiento, y los dias que
quedan van en color. Un plazo incumplido en esta materia no es un retraso
interno: es una queja ante la Superintendencia de Industria y Comercio.
"""

from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from apps.common.utils.admin import GeneralAdminModel

from .models import PQRSRequest


class OverdueFilter(admin.SimpleListFilter):
    """
    El filtro que de verdad se usa: que esta vencido y que esta por vencer.

    No se puede hacer con `list_filter` sobre un campo porque "vencido"
    depende de hoy, no de un valor guardado.
    """

    title = _('deadline')
    parameter_name = 'deadline'

    def lookups(self, request, model_admin):
        return (
            ('overdue', _('Overdue')),
            ('soon', _('Due within 3 business days')),
            ('open', _('Open')),
        )

    def queryset(self, request, queryset):
        from django.utils import timezone

        from .deadlines import add_business_days

        today = timezone.localdate()

        closed = (
            PQRSRequest.StatusChoices.ANSWERED,
            PQRSRequest.StatusChoices.WITHDRAWN,
            PQRSRequest.StatusChoices.TRANSFERRED,
        )

        if self.value() == 'overdue':
            return queryset.exclude(status__in=closed).filter(
                due_on__lt=today)

        if self.value() == 'soon':
            return queryset.exclude(status__in=closed).filter(
                due_on__gte=today,
                due_on__lte=add_business_days(today, 3),
            )

        if self.value() == 'open':
            return queryset.exclude(status__in=closed)

        return queryset


@admin.register(PQRSRequest)
class PQRSRequestAdmin(GeneralAdminModel):

    list_display = (
        'radicado', 'request_type', 'display_name', 'received_on',
        'deadline_badge', 'status',
    )
    list_filter = (OverdueFilter, 'status', 'request_type', 'person_type')
    search_fields = ('radicado', 'first_name', 'last_name', 'company_name',
                     'email', 'description')
    date_hierarchy = 'received_on'

    # Por vencimiento, no por radicacion: una consulta de ayer puede vencer
    # antes que un reclamo de la semana pasada.
    ordering = ('due_on',)

    readonly_fields = (
        'radicado', 'received_on', 'due_on', 'deadline_badge',
        'request_type', 'person_type',
        'first_name', 'last_name', 'company_name', 'legal_representative',
        'identification_type', 'identification_number',
        'country', 'city', 'address', 'email', 'phone_code', 'phone_number',
        'identity_document', 'legal_existence_document',
        'description', 'use_titular_contact', 'contact_email',
        'contact_phone', 'contact_landline',
        'accepted_terms', 'accepted_at', 'submitted_ip',
        'created', 'updated',
    )

    fieldsets = (
        (_('Filing'), {
            'fields': ('radicado', 'request_type', 'received_on', 'due_on',
                       'deadline_badge', 'status', 'extended'),
        }),
        (_('Who is filing'), {
            'fields': ('person_type', 'first_name', 'last_name',
                       'company_name', 'legal_representative',
                       'identification_type', 'identification_number',
                       'identity_document', 'legal_existence_document'),
        }),
        (_('Where to reach them'), {
            'fields': ('country', 'city', 'address', 'email', 'phone_code',
                       'phone_number', 'use_titular_contact', 'contact_email',
                       'contact_phone', 'contact_landline'),
        }),
        (_('The request'), {
            'fields': ('description',),
        }),
        (_('Handling'), {
            'fields': ('answer', 'answered_by', 'answered_at',
                       'internal_notes'),
        }),
        (_('Record of the authorisation'), {
            'classes': ('collapse',),
            'fields': ('accepted_terms', 'accepted_at', 'submitted_ip',
                       'created', 'updated'),
            'description': _(
                'Article 9 of Law 1581 requires keeping proof of the '
                'authorisation. A ticked box is not proof unless when and '
                'from where is recorded.'
            ),
        }),
    )

    def has_add_permission(self, request):
        """
        No se radica desde el panel.

        Una solicitud creada a mano no tendria constancia de la autorizacion
        del titular, que es justo lo que hay que conservar.
        """
        return False

    def has_delete_permission(self, request, obj=None):
        """
        Tampoco se borra. Es la traza de un derecho ejercido y de un plazo:
        borrarla es quedarse sin la prueba de que se respondio a tiempo.
        """
        return False

    @admin.display(description=_('Deadline'), ordering='due_on')
    def deadline_badge(self, obj):
        closed = (
            PQRSRequest.StatusChoices.ANSWERED,
            PQRSRequest.StatusChoices.WITHDRAWN,
            PQRSRequest.StatusChoices.TRANSFERRED,
        )

        if obj.status in closed:
            return format_html(
                '<span style="color:#6c757d">{}</span>',
                obj.due_on.strftime('%d/%m/%Y'),
            )

        left = obj.business_days_left

        if left < 0:
            colour, label = '#a11a1a', _('%(days)s business days overdue') % {
                'days': abs(left)}
        elif left <= 3:
            colour, label = '#a17f1a', _('%(days)s business days left') % {
                'days': left}
        else:
            colour, label = '#1a7f37', _('%(days)s business days left') % {
                'days': left}

        return format_html(
            '<b style="color:{}">{}</b><br><small>{}</small>',
            colour, obj.due_on.strftime('%d/%m/%Y'), label,
        )

    @admin.display(description=_('Who'))
    def display_name(self, obj):
        return obj.display_name

    actions = ['extend_deadline']

    @admin.action(description=_('Extend the deadline (once, as the law allows)'))
    def extend_deadline(self, request, queryset):
        from django.core.exceptions import ValidationError

        extended, refused = 0, 0

        for item in queryset:
            try:
                item.extend()
                extended += 1
            except ValidationError:
                refused += 1

        if extended:
            self.message_user(request, _(
                '%(count)s extended. Remember the law also requires telling '
                'the person why and giving them the new date.'
            ) % {'count': extended})

        if refused:
            self.message_user(request, _(
                '%(count)s were already extended: the law allows one '
                'extension only.'
            ) % {'count': refused}, level='WARNING')
