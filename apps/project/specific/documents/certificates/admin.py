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


@admin.register(UserVerificationModel)
class UserVerificationModelAdmin(GeneralAdminModel):
    actions = [
        action_set_idoneity,
        action_set_em_ipcon,
        action_set_em_propensiones,
    ]

    list_display = (
        'uuid_prefix',
        'full_name',
        'certificate_type',
        'total_views',
        'approved',
        'is_expired',
        'is_revoked',
        'expires_at',
        'detail_link',
    )

    list_display_links = ('uuid_prefix', 'full_name')

    list_filter = (
        'certificate_type',
        'approved',
        'expires_at',
        'revoked_at',
        'created',
    )

    search_fields = (
        'id',
        'public_uuid',
        'uuid_prefix',
        'public_code',
        'name',
        'last_name',
        'document_number_cc_hash',
        'document_number_pa_hash',
        'user__email',
    )

    readonly_fields = (
        'id',
        'public_uuid',
        'uuid_prefix',
        'public_code',
        'document_number_cc_hash',
        'document_number_pa_hash',
        'created',
        'updated',
        'total_views',
        'unique_views',
        'is_expired',
        'is_revoked',
    )

    fieldsets = (
        (_("Identification"), {
            "fields": (
                'public_uuid',
                'uuid_prefix',
                'public_code',
                'certificate_type',
            )
        }),
        (_("User / Holder"), {
            "fields": (
                'user',
                'name',
                'last_name',
            )
        }),
        (_("Documents"), {
            "fields": (
                'document_number_cc',
                'document_number_cc_hash',
                'document_number_pa',
                'document_number_pa_hash',
                'passport_expiration_date',
            )
        }),
        (_("Legal status"), {
            "fields": (
                'approved',
                'approved_by',
                'approval_date',
                'revoked_at',
                'revocation_reason',
            )
        }),
        (_("Validity"), {
            "fields": (
                'issued_at',
                'expires_at',
                'is_expired',
                'is_revoked',
            )
        }),
        (_("Metrics"), {
            "fields": (
                'total_views',
                'unique_views',
            )
        }),
        (_("Audit"), {
            "fields": (
                'created',
                'updated',
            )
        }),
    )

    def full_name(self, obj):
        return f"{obj.name} {obj.last_name}"
    full_name.short_description = _("Full name")

    def detail_link(self, obj):
        url = reverse(
            'certificates:detail_employee_verification_ipcon',
            args=[obj.pk]
        )
        return format_html('<a href="{}">View</a>', url)

@admin.register(DocumentVerificationModel)
class DocumentVerificationModelAdmin(GeneralAdminModel):
    actions = [action_set_aegis, action_set_generic]

    list_display = (
        'uuid_prefix',
        'document_title',
        'certificate_type',
        'total_views',
        'delivery_method',
        'is_expired',
        'expires_at',
    )

    list_display_links = ('uuid_prefix', 'document_title')

    list_filter = (
        'certificate_type',
        'delivery_method',
        'expires_at',
        'created',
    )

    search_fields = (
        'id',
        'public_code',
        'uuid_prefix',
        'document_title',
        'document_hash',
    )

    readonly_fields = (
        'id',
        'uuid_prefix',
        'public_code',
        'document_hash',
        'total_views',
        'unique_views',
        'created',
        'updated',
        'is_expired',
    )

    fieldsets = (
        (_("Identification"), {
            "fields": (
                'uuid_prefix',
                'public_code',
                'certificate_type',
            )
        }),
        (_("Document"), {
            "fields": (
                'document_title',
                'document_file',
                'document_hash',
            )
        }),
        (_("Delivery"), {
            "fields": (
                'delivery_method',
                'sent_at',
            )
        }),
        (_("Validity"), {
            "fields": (
                'issued_at',
                'expires_at',
                'is_expired',
            )
        }),
        (_("Metrics"), {
            "fields": (
                'total_views',
                'unique_views',
            )
        }),
        (_("Audit"), {
            "fields": (
                'created',
                'updated',
            )
        }),
    )

@admin.register(CertificateViewLogModel)
class CertificateViewLogModelAdmin(GeneralAdminModel):

    list_display = (
        'viewed_at',
        'target_type',
        'target_name',
        'viewer',
        'ip_address',
    )

    list_filter = (
        'viewed_at',
        'certificate_user__certificate_type',
        'document_verification__certificate_type',
    )

    search_fields = (
        'ip_address',
        'anonymous_email',
        'user__email',
        'certificate_user__name',
        'certificate_user__last_name',
        'document_verification__document_title',
    )

    readonly_fields = (
        'certificate_user',
        'document_verification',
        'user',
        'anonymous_email',
        'ip_address',
        'user_agent',
        'viewed_at',
        'created',
        'updated',
    )

    fieldsets = (
        (_("Target"), {
            "fields": (
                'certificate_user',
                'document_verification',
            )
        }),
        (_("Viewer"), {
            "fields": (
                'user',
                'anonymous_email',
                'ip_address',
            )
        }),
        (_("Technical"), {
            "fields": (
                'user_agent',
            )
        }),
        (_("Audit"), {
            "fields": (
                'viewed_at',
                'created',
                'updated',
            )
        }),
    )

    def target_type(self, obj):
        return _("User Certificate") if obj.certificate_user else _("Document Certificate")
    target_type.short_description = _("Type")

    def target_name(self, obj):
        if obj.certificate_user:
            return f"{obj.certificate_user.name} {obj.certificate_user.last_name}"
        return obj.document_verification.document_title
    target_name.short_description = _("Target")

    def viewer(self, obj):
        return obj.user or obj.anonymous_email

