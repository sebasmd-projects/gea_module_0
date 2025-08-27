from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from apps.common.utils.admin import GeneralAdminModel

from .models import CertificateModel, CertificateTypesModel


def action_set_idoneity(modeladmin, request, queryset):
    try:
        tipo_idoneity = CertificateTypesModel.objects.get(name=CertificateTypesModel.CertificateTypeChoices.IDONEITY)
        num_actualizados = queryset.update(certificate_type=tipo_idoneity)
        messages.success(
            request,
            _(f"Updated {num_actualizados} certificates to IDONEITY.")
        )
    except CertificateTypesModel.DoesNotExist:
        messages.error(
            request,
            _("Certificate type IDONEITY not found.")
        )

action_set_idoneity.short_description = _("Assign certificate type to 'IDONEITY'")


class CertificateTypesModelAdmin(GeneralAdminModel):
    
    list_display = (
        'name',
        'created',
        'updated'
    )
    search_fields = (
        'name',
    )
    fieldsets = (
        (_('Certificate Type'), {'fields': (
            'name',
        )}),
        (_('Dates'), {'fields': (
            'created',
            'updated'
        )}),
        (_('Priority'), {'fields': (
            'default_order',
        )}),
    )
    readonly_fields = (
        'created',
        'updated'
    )


class CertificateAdmin(GeneralAdminModel):
    actions = [action_set_idoneity]
    
    list_display = (
        'user',
        'name',
        'last_name',
        'certificate_type',
        'document_type',
        'document_number',
        'approved',
        'approval_date',
        'detail_link',
        'created',
        'updated'
    )
    list_display_links = list_display[:4]
    search_fields = (
        'id',
        'name',
        'last_name',
        'document_type',
        'document_number',
        'document_number_hash',
    )
    list_filter = (
        "is_active",
        "approved",
        "document_type",
        'certificate_type',
    )
    fieldsets = (
        (_('Certificate'), {'fields': (
            'user',
            'name',
            'last_name',
            'certificate_type',
            'document_type',
            'document_number',
            'document_number_hash',
            'is_active',
            'approved',
            'approval_date'
        )}),
        (_('Dates'), {'fields': (
            'created',
            'updated'
        )}),
        (_('Priority'), {'fields': (
            'default_order',
        )}),
    )
    readonly_fields = (
        'created',
        'updated',
        'document_number_hash',
    )

    def detail_link(self, obj):
        url = reverse('certificates:detail', args=[obj.pk])
        return format_html('<a href="{}">{}</a>', url, obj.pk)


admin.site.register(CertificateModel, CertificateAdmin)
admin.site.register(CertificateTypesModel, CertificateTypesModelAdmin)
