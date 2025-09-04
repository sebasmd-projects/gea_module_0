from django.contrib import admin
from django.db import models
from django.utils.translation import gettext_lazy as _
from import_export.admin import ImportExportActionModelAdmin

from apps.project.common.users.models import UserModel
from apps.project.specific.assets_management.buyers.models import OfferModel


@admin.register(OfferModel)
class OfferModelAdmin(ImportExportActionModelAdmin, admin.ModelAdmin):
    autocomplete_fields = (
        'created_by',
        'asset',
        'buyer_country',
    )

    list_display = (
        'created_by',
        'asset',
        'offer_type',
        'quantity_type',
        'is_active',
        'is_approved',
        'reviewed',
        'display',
    )

    list_filter = (
        'is_active',
        'is_approved',
        'reviewed',
        'display',
    )

    search_fields = (
        'created_by__username',
        'created_by__email',
        'asset__asset_name__es_name',
        'asset__asset_name__en_name',
        'quantity_type',
    )

    readonly_fields = (
        'created',
        'updated',
        'approved_by_timestamp',
        'reviewed_by_timestamp',
    )

    fieldsets = (
        (_('Required Fields'), {
            'fields': (
                'created_by',
                'asset',
                'offer_type',
                'quantity_type',
                'offer_amount',
                'offer_quantity',
                'buyer_country',
            ),
        }),
        (_('Approval'), {
            'fields': (
                'approved_by',
                'reviewed_by',
                'is_approved',
                'is_active',
                'reviewed',
                'display',
            ),
        }),
        (_('Dates'), {
            'fields': (
                'created',
                'updated',
                'approved_by_timestamp',
                'reviewed_by_timestamp',
            ),
            'classes': (
                'collapse',
            ),
        }),
    )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "approved_by":
            kwargs["queryset"] = UserModel.objects.filter(
                models.Q(is_superuser=True) |
                models.Q(user_permissions__codename="can_approve_offer") |
                models.Q(groups__permissions__codename="can_approve_offer")
            ).distinct()

        if db_field.name == "reviewed_by":
            kwargs["queryset"] = UserModel.objects.filter(
                models.Q(is_superuser=True) |
                models.Q(user_permissions__codename="can_review_offer") |
                models.Q(groups__permissions__codename="can_review_offer")
            ).distinct()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
