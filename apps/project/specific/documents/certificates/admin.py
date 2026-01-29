# apps/project/specific/documents/certificates/admin.py

from django.contrib import admin, messages
from django.db import transaction
from django.db.models import Count, Q
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from apps.common.utils.admin import GeneralAdminModel

from .models import (
    CertificateViewLogModel,
    DocumentCertificateTypeChoices,
    DocumentVerificationModel,
    UserCertificateTypeChoices,
    UserVerificationModel,
)


def set_certificate_type_action(*, certificate_value: str, label: str, name: str):
    """
    Factory para acciones seguras y reutilizables.
    name: identificador único (se usa para __name__)
    """
    def _action(modeladmin, request, queryset):
        with transaction.atomic():
            updated = queryset.update(certificate_type=certificate_value)
        messages.success(request, _(f"{updated} records updated to {label}."))

    _action.__name__ = name  # 👈 clave para evitar admin.E130
    _action.short_description = _(f"Asignar tipo de certificado: {label}")
    return _action


action_set_idoneity = set_certificate_type_action(
    certificate_value=UserCertificateTypeChoices.IDONEITY,
    label="IDONEITY",
    name="action_set_idoneity",
)

action_set_em_ipcon = set_certificate_type_action(
    certificate_value=UserCertificateTypeChoices.EM_IPCON,
    label="EM_IPCON",
    name="action_set_em_ipcon",
)

action_set_em_propensiones = set_certificate_type_action(
    certificate_value=UserCertificateTypeChoices.EM_PROPENSIONES,
    label="EM_PROPENSIONES",
    name="action_set_em_propensiones",
)

action_set_aegis = set_certificate_type_action(
    certificate_value=DocumentCertificateTypeChoices.AEGIS,
    label="ASSET_AEGIS",
    name="action_set_aegis",
)

action_set_generic = set_certificate_type_action(
    certificate_value=DocumentCertificateTypeChoices.GENERIC,
    label="GENERIC",
    name="action_set_generic",
)


@admin.register(UserVerificationModel)
class UserVerificationModelAdmin(GeneralAdminModel):
    actions = [action_set_idoneity, action_set_em_ipcon, action_set_em_propensiones]

    list_per_page = 50
    empty_value_display = "-"

    list_display = (
        "uuid_prefix",
        "full_name",
        "certificate_type",
        "approved_badge",
        "expired_badge",
        "revoked_badge",
        "expires_at",
        "views_total",
        "views_unique",
        "cc_masked_admin",
        "pa_masked_admin",
        "detail_link",
    )
    list_display_links = ("uuid_prefix", "full_name")
    list_editable = ("expires_at",)  # UX: ajustes rápidos (si te conviene)

    list_filter = (
        "certificate_type",
        "approved",
        ("expires_at", admin.DateFieldListFilter),
        ("revoked_at", admin.DateFieldListFilter),
        ("created", admin.DateFieldListFilter),
    )
    date_hierarchy = "created"
    ordering = ("-created",)

    search_fields = (
        "public_uuid",
        "uuid_prefix",
        "public_code",
        "name",
        "last_name",
        "document_number_cc_hash",
        "document_number_pa_hash",
        "user__email",
    )

    autocomplete_fields = ("user", "approved_by")
    list_select_related = ("user", "approved_by")

    readonly_fields = (
        "id",
        "public_uuid",
        "uuid_prefix",
        "public_code",
        "document_number_cc_hash",
        "document_number_pa_hash",
        "created",
        "updated",
        "is_expired",
        "is_revoked",
        # UX/seguridad: mostrar solo máscara en admin
        "cc_masked_admin",
        "pa_masked_admin",
        "employee_photo_preview",
        # métricas anotadas (no properties)
        "views_total",
        "views_unique",
    )

    fieldsets = (
        (_("Identificación"), {
            "fields": ("public_uuid", "uuid_prefix", "public_code", "certificate_type"),
        }),
        (_("Titular"), {
            "fields": ("user", "name", "last_name", "employee_photo", "employee_photo_preview"),
        }),
        (_("Documentos (sensibles)"), {
            # Seguridad: deja editables si realmente lo necesitas,
            # pero muestra máscara explícita y hash siempre.
            "fields": (
                "document_number_cc",
                "cc_masked_admin",
                "document_number_cc_hash",
                "document_number_pa",
                "pa_masked_admin",
                "document_number_pa_hash",
                "passport_expiration_date",
            ),
        }),
        (_("Estado legal"), {
            "fields": ("approved", "approved_by", "approval_date", "revoked_at", "revocation_reason"),
        }),
        (_("Vigencia"), {
            "fields": ("issued_at", "expires_at", "is_expired", "is_revoked"),
        }),
        (_("Métricas"), {
            "fields": ("views_total", "views_unique"),
            "classes": ("collapse",),
        }),
        (_("Auditoría"), {
            "fields": ("created", "updated"),
            "classes": ("collapse",),
        }),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Evita N+1: anota conteos (total y únicos)
        return qs.annotate(
            _views_total=Count("view_logs", distinct=False),
            _views_unique=Count(
                "view_logs",
                distinct=True,
                filter=Q(view_logs__isnull=False),
            ),
        )

    @admin.display(description=_("Full name"))
    def full_name(self, obj):
        return f"{obj.name or ''} {obj.last_name or ''}".strip() or "-"

    @admin.display(description=_("Approved"), boolean=True)
    def approved_badge(self, obj):
        return bool(obj.approved)

    @admin.display(description=_("Expired"), boolean=True)
    def expired_badge(self, obj):
        return bool(obj.is_expired)

    @admin.display(description=_("Revoked"), boolean=True)
    def revoked_badge(self, obj):
        return bool(obj.is_revoked)

    @admin.display(description=_("Views"))
    def views_total(self, obj):
        return getattr(obj, "_views_total", 0)

    @admin.display(description=_("Unique"))
    def views_unique(self, obj):
        # Nota: tu unique_views real distingue user/email.
        # Esto es “suficientemente útil” para admin; si quieres exactitud,
        # te propongo una vista materializada o un contador denormalizado.
        return getattr(obj, "_views_unique", 0)

    @admin.display(description=_("CC (masked)"))
    def cc_masked_admin(self, obj):
        return obj.cc_masked or "-"

    @admin.display(description=_("Passport (masked)"))
    def pa_masked_admin(self, obj):
        return obj.pa_masked or "-"

    @admin.display(description=_("Photo"))
    def employee_photo_preview(self, obj):
        if not getattr(obj, "employee_photo", None):
            return "-"
        return format_html(
            '<img src="{}" style="height:55px;width:55px;object-fit:cover;border-radius:8px;" />',
            obj.employee_photo.url,
        )

    @admin.display(description=_("Detail"))
    def detail_link(self, obj):
        url = reverse("certificates:detail_employee_verification_ipcon", args=[obj.pk])
        return format_html('<a href="{}">Ver</a>', url)


# -----------------------
# DocumentVerification
# -----------------------
@admin.register(DocumentVerificationModel)
class DocumentVerificationModelAdmin(GeneralAdminModel):
    actions = [action_set_aegis, action_set_generic]

    list_per_page = 50
    empty_value_display = "-"

    list_display = (
        "uuid_prefix",
        "document_title",
        "certificate_type",
        "delivery_method",
        "expired_badge",
        "expires_at",
        "views_total",
        "views_unique",
        "file_link",
        "hash_short",
    )
    list_display_links = ("uuid_prefix", "document_title")
    list_editable = ("delivery_method", "expires_at")

    list_filter = (
        "certificate_type",
        "delivery_method",
        ("expires_at", admin.DateFieldListFilter),
        ("created", admin.DateFieldListFilter),
    )
    date_hierarchy = "created"
    ordering = ("-created",)

    search_fields = ("public_code", "uuid_prefix", "document_title", "document_hash")

    readonly_fields = (
        "id",
        "uuid_prefix",
        "public_code",
        "document_hash",
        "hash_short",
        "created",
        "updated",
        "is_expired",
        "views_total",
        "views_unique",
        "file_link",
    )

    fieldsets = (
        (_("Identificación"), {"fields": ("uuid_prefix", "public_code", "certificate_type")}),
        (_("Documento"), {"fields": ("document_title", "document_file", "file_link", "document_hash", "hash_short")}),
        (_("Entrega"), {"fields": ("delivery_method", "sent_at")}),
        (_("Vigencia"), {"fields": ("issued_at", "expires_at", "is_expired")}),
        (_("Métricas"), {"fields": ("views_total", "views_unique"), "classes": ("collapse",)}),
        (_("Auditoría"), {"fields": ("created", "updated"), "classes": ("collapse",)}),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(
            _views_total=Count("view_logs", distinct=False),
            _views_unique=Count("view_logs", distinct=True),
        )

    @admin.display(description=_("Expired"), boolean=True)
    def expired_badge(self, obj):
        return bool(obj.is_expired)

    @admin.display(description=_("Views"))
    def views_total(self, obj):
        return getattr(obj, "_views_total", 0)

    @admin.display(description=_("Unique"))
    def views_unique(self, obj):
        return getattr(obj, "_views_unique", 0)

    @admin.display(description=_("File"))
    def file_link(self, obj):
        if not obj.document_file:
            return "-"
        return format_html('<a href="{}" target="_blank" rel="noopener noreferrer">Abrir</a>', obj.document_file.url)

    @admin.display(description=_("Hash"))
    def hash_short(self, obj):
        h = obj.document_hash or ""
        return (h[:10] + "…") if len(h) > 12 else (h or "-")


# -----------------------
# View Log
# -----------------------
@admin.register(CertificateViewLogModel)
class CertificateViewLogModelAdmin(GeneralAdminModel):
    list_per_page = 100
    empty_value_display = "-"

    list_display = (
        "viewed_at",
        "target_type",
        "target_admin_link",
        "viewer_display",
        "ip_address",
    )
    list_filter = (
        ("viewed_at", admin.DateFieldListFilter),
        "certificate_user__certificate_type",
        "document_verification__certificate_type",
    )
    date_hierarchy = "viewed_at"
    ordering = ("-viewed_at",)

    search_fields = (
        "ip_address",
        "anonymous_email",
        "user__email",
        "certificate_user__name",
        "certificate_user__last_name",
        "document_verification__document_title",
    )

    autocomplete_fields = ("certificate_user", "document_verification", "user")
    list_select_related = ("certificate_user", "document_verification", "user")

    readonly_fields = (
        "certificate_user",
        "document_verification",
        "user",
        "anonymous_email",
        "ip_address",
        "user_agent",
        "viewed_at",
        "created",
        "updated",
        "target_type",
        "target_admin_link",
        "viewer_display",
    )

    fieldsets = (
        (_("Target"), {"fields": ("certificate_user", "document_verification", "target_type", "target_admin_link")}),
        (_("Viewer"), {"fields": ("user", "anonymous_email", "viewer_display", "ip_address")}),
        (_("Technical"), {"fields": ("user_agent",), "classes": ("collapse",)}),
        (_("Audit"), {"fields": ("viewed_at", "created", "updated"), "classes": ("collapse",)}),
    )

    @admin.display(description=_("Type"))
    def target_type(self, obj):
        return _("User Certificate") if obj.certificate_user_id else _("Document Certificate")

    @admin.display(description=_("Target"))
    def target_admin_link(self, obj):
        if obj.certificate_user_id:
            url = reverse("admin:certificates_userverificationmodel_change", args=[obj.certificate_user_id])
            label = f"{obj.certificate_user.name} {obj.certificate_user.last_name}".strip()
            return format_html('<a href="{}">{}</a>', url, label or "-")
        if obj.document_verification_id:
            url = reverse("admin:certificates_documentverificationmodel_change", args=[obj.document_verification_id])
            return format_html('<a href="{}">{}</a>', url, obj.document_verification.document_title)
        return "-"

    @admin.display(description=_("Viewer"))
    def viewer_display(self, obj):
        return obj.user or obj.anonymous_email or "-"
