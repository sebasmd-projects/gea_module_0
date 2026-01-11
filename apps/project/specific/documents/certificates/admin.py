from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from apps.common.utils.admin import GeneralAdminModel

from .models import (CertificateViewLogModel, DocumentCertificateTypeChoices,
                     DocumentVerificationModel, UserCertificateTypeChoices,
                     UserVerificationModel)


def action_set_certificate_type(request, queryset, certificate_type, model):
    try:
        num_actualizados = queryset.update(certificate_type=certificate_type)
        messages.success(
            request,
            _(f"Updated {num_actualizados} certificates to {certificate_type.name}.")
        )
    except model.DoesNotExist:
        messages.error(
            request,
            _(f"Certificate type {certificate_type.name} not found.")
        )


def action_set_idoneity(modeladmin, request, queryset):
    action_set_certificate_type(
        request, queryset, UserCertificateTypeChoices.IDONEITY, UserCertificateTypeChoices)


def action_set_em_ipcon(modeladmin, request, queryset):
    action_set_certificate_type(
        request, queryset, UserCertificateTypeChoices.EM_IPCON, UserCertificateTypeChoices)


def action_set_em_propensiones(modeladmin, request, queryset):
    action_set_certificate_type(
        request, queryset, UserCertificateTypeChoices.EM_PROPENSIONES, UserCertificateTypeChoices)


def action_set_aegis(modeladmin, request, queryset):
    action_set_certificate_type(
        request, queryset, DocumentCertificateTypeChoices.AEGIS, DocumentVerificationModel)


def action_set_generic(modeladmin, request, queryset):
    action_set_certificate_type(
        request, queryset, DocumentCertificateTypeChoices.GENERIC, DocumentVerificationModel)


action_set_idoneity.short_description = _(
    "Assign user certificate type to 'IDONEITY'")
action_set_em_ipcon.short_description = _(
    "Assign user certificate type to 'EM_IPCON'")
action_set_em_propensiones.short_description = _(
    "Assign user certificate type to 'EM_PROPENSIONES'")
action_set_aegis.short_description = _(
    "Assign document certificate type to 'AEGIS'")
action_set_generic.short_description = _(
    "Assign document certificate type to 'GENERIC'")


class UserVerificationModelAdmin(GeneralAdminModel):
    actions = [action_set_idoneity, action_set_em_ipcon,
               action_set_em_propensiones, action_set_aegis, action_set_generic]

    list_display = (
        'id',
        'certificate_type',
        'detail_link',
        'uuid_prefix'
    )

    search_fields = (
        'id',
        'name',
        'last_name',
    )

    list_filter = (
        "is_active",
        "approved"
    )

    readonly_fields = (
        'created',
        'updated',
    )

    def detail_link(self, obj):
        url = reverse(
            'certificates:detail_employee_verification_ipcon', args=[obj.pk])
        return format_html('<a href="{}">{}</a>', url, obj.pk)


class DocumentVerificationModelAdmin(GeneralAdminModel):
    actions = [action_set_aegis, action_set_generic]

    list_display = (
        'id',
        'document_title',
        'public_code',
        'uuid_prefix',
        'certificate_type'
    )

    search_fields = (
        'id',
        'document_title',
        'public_code',
        'uuid_prefix',
    )

    list_filter = (
        "is_active",
    )

    readonly_fields = (
        'created',
        'updated',
    )

    # def detail_link(self, obj):
    #     url = reverse('certificates:detail_document_verification_ipcon', args=[obj.pk])
    #     return format_html('<a href="{}">{}</a>', url, obj.pk)


class CertificateViewLogModelAdmin(GeneralAdminModel):

    search_fields = (
        'id',
        'user_verification__name',
        'user_verification__last_name',
        'document_verification__document_name',
    )

    list_filter = (
        "viewed_at",
    )

    readonly_fields = (
        'created',
        'updated',
    )


admin.site.register(UserVerificationModel, UserVerificationModelAdmin)
admin.site.register(DocumentVerificationModel, DocumentVerificationModelAdmin)
admin.site.register(CertificateViewLogModel, CertificateViewLogModelAdmin)
