from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from import_export.admin import ImportExportActionModelAdmin
from django.db import models

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
    )

    list_filter = (
        'is_active',
        'is_approved',
        'reviewed',
    )

    search_fields = (
        'created_by',
        'asset',
        'offer_type',
        'quantity_type',
    )

    readonly_fields = (
        'created',
        'updated',
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
                'is_approved',
                'is_active',
                'reviewed',
            ),
        }),
        (_('Dates'), {
            'fields': (
                'created',
                'updated',
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
                models.Q(user_permissions__codename="can_approve_offer")
            ).distinct()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
