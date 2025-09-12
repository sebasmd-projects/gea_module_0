# apps.project.specific.assets_management.buyers.admin.py
from django.contrib import admin
from django.db import models
from django.utils.translation import gettext_lazy as _
from import_export.admin import ImportExportActionModelAdmin

from apps.project.common.users.models import UserModel
from apps.project.specific.assets_management.buyers.models import OfferModel


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
    )
    
    list_display = (
        "created_by",
        "asset",
        "buyer_country",
        "offer_type",
        "quantity_type",
        "offer_quantity",
        "offer_amount",
        "is_active",
        "display",
        "is_approved",
        "reviewed",
    )

    list_filter = (
        "is_active",
        "display",
        "is_approved",
        "reviewed",
        "offer_type",
        "quantity_type",
        "buyer_country",
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
    )

    fieldsets = (
        (_("Required Fields"), {
            "fields": (
                "created_by",
                "asset",
                "offer_type",
                "quantity_type",
                "offer_amount",
                "offer_quantity",
                "buyer_country",
                "display",
                "is_active",
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

        return super().formfield_for_foreignkey(db_field, request, **kwargs)
