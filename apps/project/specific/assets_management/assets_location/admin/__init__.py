from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from apps.common.utils.admin import GeneralAdminModel

from ..models import AssetCountryModel, AssetLocationModel, LocationModel


@admin.register(AssetCountryModel)
class AssetCountryAdmin(GeneralAdminModel):
    list_display = (
        'continent',
        'es_country_name',
        'en_country_name',
        'is_active',
    )

    search_fields = (
        'continent',
        'es_country_name',
        'en_country_name',
    )

    readonly_fields = (
        'id',
        'created',
        'updated',
    )

    fieldsets = (
        (_('Required Fields'), {
            'fields': (
                'id',
                'continent',
                'es_country_name',
                'en_country_name',
                'is_active',
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
        (
            _('Priority'), {
                'fields': (
                    'default_order',
                ),
                'classes': (
                    'collapse',
                )
            }
        )
    )


@admin.register(AssetLocationModel)
class AssetLocationAdmin(GeneralAdminModel):

    autocomplete_fields = (
        'created_by',
        'asset',
        'location',
    )

    autocomplete_fields = (
        'asset',
        'location'
    )

    search_fields = (
        'location__reference',
        'asset__asset_name__es_name',
        'amount',
        'created_by__username',
        'created_by__email',
        'created_by__first_name',
        'created_by__last_name',
    )

    list_display = (
        'created_by',
        'get_location_reference',
        'get_location_country',
        'amount',
        'get_asset_es_name',
        'is_active',
    )

    list_display_links = list_display[:3]

    readonly_fields = (
        'id',
        'created',
        'updated'
    )

    ordering = (
        'location',
        'asset',
        'created'
    )

    fieldsets = (
        (_('Required Fields'), {
            'fields': (
                'id',
                'created_by',
                'asset',
                'location',
                'quantity_type',
                'amount',
                'is_active',
                'observations_es',
                'observations_en',
            ),
        }),
        (_('Dates'), {
            'fields': (
                'created',
                'updated'
            ),
            'classes': (
                'collapse',
            )
        }),
        (
            _('Priority'), {
                'fields': (
                    'default_order',
                ),
                'classes': (
                    'collapse',
                )
            }
        )
    )

    def get_asset_es_name(self, obj):
        return obj.asset.asset_name.es_name

    def get_location_reference(self, obj):
        return obj.location.reference

    def get_location_country(self, obj):
        return obj.location.country.es_country_name

    get_asset_es_name.short_description = _("Asset Name (ES)")
    get_location_reference.short_description = _("Reference")
    get_location_country.short_description = _("Country")


@admin.register(LocationModel)
class LocationModelAdmin(GeneralAdminModel):
    autocomplete_fields = (
        'created_by',
        'country',
    )

    list_display = (
        'created_by',
        'reference',
        'country',
        'created_by',
        'is_active',
    )

    search_fields = (
        'reference',
        'country__country_name',
        'created_by__username',
        'created_by__email'
    )

    list_filter = (
        'country__continent',
    )

    ordering = (
        'country',
        'reference',
        '-created'
    )

    readonly_fields = (
        'id',
        'created',
        'updated'
    )

    fieldsets = (
        (_('User Field'), {
            'fields': (
                'created_by',
            ),
        }),
        (_('Required Fields'), {
            'fields': (
                'id',
                'reference',
                'country',
                'is_active',
            )
        }),
        (_('Optional Fields'), {
            'fields': (
                'description_es',
                'description_en',
            ),
            'classes': (
                'collapse',
            )
        }),
        (_('Dates'), {
            'fields': (
                'created',
                'updated'
            ),
            'classes': (
                'collapse',
            )
        }),
        (
            _('Priority'), {
                'fields': (
                    'default_order',
                ),
                'classes': (
                    'collapse',
                )
            }
        )
    )
