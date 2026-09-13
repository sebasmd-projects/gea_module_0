import json
from datetime import timedelta

from django.conf import settings
from django.contrib import admin, messages
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from import_export.admin import ImportExportActionModelAdmin

from .blocking import block_duration, describe_duration
from .models import GeaDailyUniqueCode, IPBlockedModel, WhiteListedIPModel


class GeneralAdminModel(ImportExportActionModelAdmin, admin.ModelAdmin):
    list_per_page = 100
    max_list_per_page = 2000
    
    def format_thousands(self, value, decimals=0):
        try:
            if decimals > 0:
                s = f"{float(value):,.{decimals}f}"
            else:
                s = f"{int(value):,}"
            return s.replace(',', ".")
        except (TypeError, ValueError):
            return value
    
    
    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['list_per_page_options'] = [10, 50, 100, 1000]

        list_per_page_value = request.GET.get('list_per_page')
        if list_per_page_value:
            try:
                list_per_page_value = int(list_per_page_value)
                if list_per_page_value > self.max_list_per_page:
                    messages.warning(
                        request,
                        _(f"Maximum allowed: {self.max_list_per_page} records.")
                    )
                    list_per_page_value = self.max_list_per_page
                elif list_per_page_value < 1:
                    messages.warning(request, _("Minimum allowed: 1 record."))
                    list_per_page_value = 1
                self.list_per_page = list_per_page_value
            except ValueError:
                messages.error(request, _("Please enter a valid number."))
        return super().changelist_view(request, extra_context=extra_context)


@admin.register(GeaDailyUniqueCode)
class GeaDailyUniqueCodeAdmin(admin.ModelAdmin):
    list_display = ("valid_on", "kind", "code", "is_active", "sent_at")
    search_fields = ("code",)
    list_filter = ("is_active", "valid_on")
    readonly_fields = (
        "sent_at", "sent_to",
        "last_email_message_id", "created", "updated"
    )


@admin.register(IPBlockedModel)
class IPBlockedModelAdmin(GeneralAdminModel):
    """
    La tabla de bloqueos, para poder leerla sin abrir cada fila.

    Antes la primera columna era el ``session_info`` entero --un JSON crudo,
    con cabeceras y parametros dentro, en la celda-- y todo lo demas habia que
    deducirlo de el. No se podia ordenar por intentos, ni filtrar las que
    vienen de un proveedor cloud, ni ver de un vistazo si un bloqueo sigue en
    pie. El JSON esta ahora donde le corresponde: dentro de la ficha, como
    rastro crudo, y en el listado van las columnas.

    El orden es por **fecha de alta y despues por actualizacion**, de lo mas
    nuevo a lo mas viejo. Y las columnas son ordenables: para ver «lo ultimo
    que se movio» basta con pulsar en `last detection`, que es una fecha
    distinta de `updated` -- esa la mueve cualquier guardado, incluido uno
    hecho a mano desde aqui.
    """

    list_display = (
        'current_ip', 'block_state', 'attempt_count', 'unique_paths',
        'origin', 'reason', 'matched_pattern', 'agent', 'first_seen',
        'last_seen',
    )
    list_display_links = ('current_ip',)
    ordering = ('-created', '-updated')
    date_hierarchy = 'created'

    list_filter = (
        'is_datacenter', 'reason', 'is_active', 'country', 'network_owner',
        'created',
    )
    search_fields = (
        'current_ip', 'user_agent', 'matched_pattern', 'network_owner',
        'session_info',
    )

    readonly_fields = (
        'pretty_session_info', 'created', 'updated', 'first_seen', 'last_seen',
        'attempt_count', 'unique_paths', 'user_agent', 'matched_pattern',
        'country', 'network_owner', 'is_datacenter', 'block_state',
        'block_length',
    )

    fieldsets = (
        (
            _('Block'), {
                'fields': (
                    'current_ip',
                    'reason',
                    'is_active',
                    'block_state',
                    'blocked_until',
                    'block_length',
                )
            }
        ),
        (
            _('Activity'), {
                'fields': (
                    'attempt_count',
                    'unique_paths',
                    'matched_pattern',
                    'user_agent',
                    'first_seen',
                    'last_seen',
                )
            }
        ),
        (
            _('Origin'), {
                'fields': (
                    'is_datacenter',
                    'network_owner',
                    'country',
                ),
                'description': _(
                    'Where the address lives. A person browses from a home or '
                    'office address; a server does not browse. This is a hint '
                    'for reading the row, never a reason to block on its own: '
                    'a commercial VPN comes out of the same ranges.'
                ),
            }
        ),
        (
            _('Raw trail'), {
                'fields': ('pretty_session_info',),
                'classes': ('collapse',),
            }
        ),
        (
            _('Times'), {
                'fields': ('created', 'updated'),
                'classes': ('collapse',),
            }
        ),
        (
            _('Other'), {
                'fields': ('language', 'default_order'),
                'classes': ('collapse',),
            }
        ),
    )

    # ------------------------------------------------------------------
    @admin.display(description=_('blocked'), boolean=False,
                   ordering='blocked_until')
    def block_state(self, obj):
        """
        Si el bloqueo esta en pie **ahora**, y cuanto le queda.

        Se calcula al pintar la fila, asi que se actualiza solo: no hay
        columna que mantener ni cron que la corrija. `is_active` por si sola
        decia «bloqueada» para siempre, porque nadie la baja cuando el reloj
        pasa -- y eso hacia que la tabla enseñara como activos bloqueos
        caducados hace meses.
        """
        if obj.is_currently_blocked:
            return mark_safe(
                '<span style="color:#b02a37;font-weight:600;">&#9679; '
                + _('Blocked') + '</span><br>'
                + '<span style="color:#6c757d;font-size:.85em;">'
                + describe_duration(obj.time_remaining) + ' '
                + _('left') + '</span>'
            )

        if not obj.is_active:
            return mark_safe(
                '<span style="color:#6c757d;">&#9675; ' + _('Disabled')
                + '</span>')

        return mark_safe(
            '<span style="color:#198754;">&#9675; ' + _('Expired') + '</span>')

    @admin.display(description=_('block length'))
    def block_length(self, obj):
        """Cuanto duraria el proximo bloqueo con los intentos que lleva."""
        base = timedelta(
            minutes=getattr(settings, 'IP_BLOCKED_TIME_IN_MINUTES', 15))

        return describe_duration(
            block_duration(max(1, obj.attempt_count), base))

    @admin.display(description=_('origin'), ordering='network_owner')
    def origin(self, obj):
        """
        Proveedor y pais, o un guion si no se sabe.

        Los dos valores van **escapados**, igual que en `agent()` de aqui
        debajo. Hoy salen de `netintel.py`, que resuelve con una tabla que
        viaja en el repositorio, pero son columnas de la fila: quedan escritas
        en la base de datos y se pintan en una pagina del panel. Una columna
        que se interpola cruda en HTML es una inyeccion esperando a que alguna
        vez se rellene desde otro sitio -- y la funcion de al lado ya lo hacia
        bien, asi que la diferencia era un descuido, no una decision.
        """
        parts = []

        if obj.is_datacenter:
            parts.append(format_html(
                '<span style="color:#b02a37;font-weight:600;">{}</span>',
                obj.network_owner or _('datacenter')))
        elif obj.network_owner:
            parts.append(escape(obj.network_owner))

        if obj.country:
            parts.append(format_html(
                '<span style="color:#6c757d;">{}</span>', obj.country))

        return mark_safe(' &middot; '.join(parts)) if parts else '—'

    @admin.display(description=_('user agent'), ordering='user_agent')
    def agent(self, obj):
        """El agente, recortado: entero rompe el ancho de la tabla."""
        if not obj.user_agent:
            return '—'

        short = obj.user_agent[:60]

        if len(obj.user_agent) > 60:
            short += '…'

        return mark_safe(
            f'<span title="{escape(obj.user_agent)}">{escape(short)}</span>')

    @admin.display(description=_('Raw trail'))
    def pretty_session_info(self, obj):
        formatted = json.dumps(obj.session_info, indent=4, ensure_ascii=False)
        return mark_safe(f"<pre>{escape(formatted)}</pre>")


@admin.register(WhiteListedIPModel)
class WhiteListedIPModelAdmin(GeneralAdminModel):
    list_display = ('current_ip', 'reason', 'is_active', 'created', 'updated')
    list_filter = ('is_active', 'reason')
    search_fields = ('current_ip', 'reason')
