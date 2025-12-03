# apps.project.specific.assets_management.buyers.admin.py
from django.contrib import admin
from django.db import models
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from import_export.admin import ImportExportActionModelAdmin

from apps.project.common.users.models import UserModel
from apps.project.specific.assets_management.buyers.models import (
    OfferModel, ServiceOrderRecipient)


@admin.register(OfferModel)
class OfferModelAdmin(ImportExportActionModelAdmin, admin.ModelAdmin):
    autocomplete_fields = (
        "created_by",
        "asset",
        "buyer_country",
        "approved_by",
        "reviewed_by",
        "service_order_sent_by",
        "payment_order_created_by",
        "payment_order_sent_by",
        "asset_in_possession_by",
        "asset_sent_by",
        "profitability_created_by",
        "profitability_paid_by",
        "recovery_repatriation_foundation_mark_by",
        "pay_master_service_mark_by",
        "propensiones_mark_by",
    )

    list_display = (
        "created_by",
        "asset",
        "buyer_country",
        "offer_type",
        "quantity_type",
        "offer_quantity",
        "is_active",
        "display",
        "is_approved",
        "reviewed",
        "profitability_all_paid",
        "recovery_repatriation_foundation_paid",
        "pay_master_service_paid",
        "propensiones_paid",
    )

    list_filter = (
        "is_active",
        "display",
        "is_approved",
        "reviewed",
        "offer_type",
        "quantity_type",
        "buyer_country",
        "recovery_repatriation_foundation_paid",
        "pay_master_service_paid",
        "propensiones_paid",
        ("created", admin.DateFieldListFilter),
        ("updated", admin.DateFieldListFilter),
    )

    search_fields = (
        "created_by__username",
        "created_by__email",
        "asset__asset_name__es_name",
        "asset__asset_name__en_name",
        "buyer_country__name",
        "en_observation",
        "es_observation",
        "en_description",
        "es_description",
    )

    readonly_fields = (
        # base timestamps
        "created",
        "updated",
        # approval / review timestamps
        "approved_by_timestamp",
        "reviewed_by_timestamp",
        # stage timestamps
        "service_order_sent_at",
        "service_order_created_by",
        "service_order_created_at",
        "payment_order_created_at",
        "payment_order_sent_at",
        "asset_in_possession_at",
        "asset_sent_at",
        "profitability_created_at",
        "profitability_paid_at",
        "recovery_repatriation_foundation_mark_at",
        "pay_master_service_mark_at",
        "propensiones_mark_at",
        # thumb img
        "image_thumb",
    )

    fieldsets = (
        (_("Required Fields"), {
            "fields": (
                "created_by",
                "asset",
                "offer_type",
                "quantity_type",
                "offer_quantity",
                "buyer_country",
                "display",
                "is_active",
            ),
        }),
        (_("Thumbnail"), {
            "fields": (
                "image_thumb",
            ),
        }),
        (_("Descriptions & Observations"), {
            "fields": (
                "en_description",
                "es_description",
                "en_observation",
                "es_observation",
            ),
            "classes": ("collapse",),
        }),
        (_("Approval & Review"), {
            "fields": (
                "approved_by",
                "approved_by_timestamp",
                "reviewed_by",
                "reviewed_by_timestamp",
                "is_approved",
                "reviewed",
            ),
        }),
        (_("Service Order"), {
            "fields": (
                "service_order_created_by",
                "service_order_created_at",
                "service_order_sent_by",
                "service_order_sent_at",
            ),
            "classes": ("collapse",),
        }),
        (_("Payment Order"), {
            "fields": (
                "payment_order_created_by",
                "payment_order_created_at",
                "payment_order_sent_by",
                "payment_order_sent_at",
            ),
            "classes": ("collapse",),
        }),
        (_("Asset Movement"), {
            "fields": (
                "asset_in_possession_by",
                "asset_in_possession_at",
                "asset_sent_by",
                "asset_sent_at",
            ),
            "classes": ("collapse",),
        }),
        (_("Profitability - Sub Payments"), {
            "fields": (
                # Recovery Repatriation Foundation
                "recovery_repatriation_foundation_paid",
                "recovery_repatriation_foundation_mark_by",
                "recovery_repatriation_foundation_mark_at",
                # PAY MASTER Service
                "pay_master_service_paid",
                "pay_master_service_mark_by",
                "pay_master_service_mark_at",
                # Propensiones
                "propensiones_paid",
                "propensiones_mark_by",
                "propensiones_mark_at",
            ),
            "classes": ("collapse",),
        }),
        (_("Profitability"), {
            "fields": (
                "profitability_created_by",
                "profitability_created_at",
                "profitability_paid_by",
                "profitability_paid_at",
            ),
            "classes": ("collapse",),
        }),
        (_("Dates"), {
            "fields": (
                "created",
                "updated",
            ),
            "classes": ("collapse",),
        }),
    )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # Aprobación
        if db_field.name == "approved_by":
            kwargs["queryset"] = UserModel.objects.filter(
                models.Q(is_superuser=True) |
                models.Q(user_permissions__codename="can_approve_offer") |
                models.Q(groups__permissions__codename="can_approve_offer")
            ).distinct()

        # Revisión
        if db_field.name == "reviewed_by":
            kwargs["queryset"] = UserModel.objects.filter(
                models.Q(is_superuser=True) |
                models.Q(user_permissions__codename="can_review_offer") |
                models.Q(groups__permissions__codename="can_review_offer")
            ).distinct()

        # Etapas:
        if db_field.name == "service_order_sent_by":
            kwargs["queryset"] = UserModel.objects.filter(
                models.Q(is_superuser=True) |
                models.Q(user_permissions__codename="can_send_service_order") |
                models.Q(groups__permissions__codename="can_send_service_order")
            ).distinct()

        if db_field.name == "payment_order_created_by":
            kwargs["queryset"] = UserModel.objects.filter(
                models.Q(is_superuser=True) |
                models.Q(user_permissions__codename="can_create_payment_order") |
                models.Q(groups__permissions__codename="can_create_payment_order")
            ).distinct()

        if db_field.name == "payment_order_sent_by":
            kwargs["queryset"] = UserModel.objects.filter(
                models.Q(is_superuser=True) |
                models.Q(user_permissions__codename="can_send_payment_order") |
                models.Q(groups__permissions__codename="can_send_payment_order")
            ).distinct()

        if db_field.name == "asset_in_possession_by":
            kwargs["queryset"] = UserModel.objects.filter(
                models.Q(is_superuser=True) |
                models.Q(user_permissions__codename="can_set_asset_possession") |
                models.Q(groups__permissions__codename="can_set_asset_possession")
            ).distinct()

        if db_field.name == "asset_sent_by":
            kwargs["queryset"] = UserModel.objects.filter(
                models.Q(is_superuser=True) |
                models.Q(user_permissions__codename="can_send_asset") |
                models.Q(groups__permissions__codename="can_send_asset")
            ).distinct()

        if db_field.name == "profitability_created_by":
            kwargs["queryset"] = UserModel.objects.filter(
                models.Q(is_superuser=True) |
                models.Q(user_permissions__codename="can_set_profitability") |
                models.Q(groups__permissions__codename="can_set_profitability")
            ).distinct()

        if db_field.name == "profitability_paid_by":
            kwargs["queryset"] = UserModel.objects.filter(
                models.Q(is_superuser=True) |
                models.Q(user_permissions__codename="can_pay_profitability") |
                models.Q(groups__permissions__codename="can_pay_profitability")
            ).distinct()

        # --- NUEVOS: limitamos quién puede marcar subpagos ---
        if db_field.name in {
            "recovery_repatriation_foundation_mark_by",
            "pay_master_service_mark_by",
            "propensiones_mark_by",
        }:
            kwargs["queryset"] = UserModel.objects.filter(
                models.Q(is_superuser=True) |
                models.Q(user_permissions__codename="can_pay_profitability") |
                models.Q(groups__permissions__codename="can_pay_profitability")
            ).distinct()

        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def image_thumb(self, obj):
        if obj.offer_img:
            return mark_safe(f'<img src="{obj.offer_img.url}" style="max-width:180px; border-radius:8px;" />')
        return "-"

    image_thumb.short_description = "Preview"


@admin.register(ServiceOrderRecipient)
class ServiceOrderRecipientAdmin(ImportExportActionModelAdmin, admin.ModelAdmin):
    list_display = (
        "id",
        "offer",
        "user",
        "user_type",
        "added_by",
        "created",
        "updated",
    )

    search_fields = (
        "offer__id",
        "offer__asset__asset_name__es_name",
        "offer__asset__asset_name__en_name",
        "user__username",
        "user__email",
        "added_by__username",
        "added_by__email",
    )

    list_filter = (
        "is_active",
    )
