import json

from django.contrib import admin, messages
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from import_export.admin import ImportExportActionModelAdmin

from .models import GeaDailyUniqueCode, IPBlockedModel, WhiteListedIPModel


class GeneralAdminModel(ImportExportActionModelAdmin, admin.ModelAdmin):
    list_per_page = 100
    max_list_per_page = 2000

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
    list_display = ('current_ip', 'session_info', 'attempt_count_display', 'reason', 'is_active',
                    'blocked_until', 'created', 'updated')
    list_filter = ('is_active', 'reason')
    search_fields = ('current_ip', 'reason', 'session_info')
    readonly_fields = ('pretty_session_info', 'created',
                       'updated', 'attempt_count_display')
    fieldsets = (
        (
            _('Information'), {
                'fields': (
                    'current_ip',
                    'reason',
                    'is_active',
                    'pretty_session_info'
                )
            }
        ),
        (
            _('Times'), {
                'fields': (
                    'created',
                    'updated',
                    'blocked_until',
                ),
                'classes': (
                    'collapse',
                )
            }
        ),
        (
            _('Other'), {
                'fields': (
                    'language',
                    'default_order',
                ),
                'classes': (
                    'collapse',
                )
            }
        ),
    )

    def pretty_session_info(self, obj):
        formatted = json.dumps(obj.session_info, indent=4)
        return mark_safe(f"<pre>{formatted}</pre>")

    def attempt_count_display(self, obj):
        return obj.session_info.get('attempt_count', 0)

    pretty_session_info.short_description = "Session Information"
    attempt_count_display.short_description = "Attempt Count"


@admin.register(WhiteListedIPModel)
class WhiteListedIPModelAdmin(GeneralAdminModel):
    list_display = ('current_ip', 'reason', 'is_active', 'created', 'updated')
    list_filter = ('is_active', 'reason')
    search_fields = ('current_ip', 'reason')
