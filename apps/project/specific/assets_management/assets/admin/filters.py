from django.contrib import admin
from django.db import models
from django.utils.translation import gettext_lazy as _


class ZeroTotalQuantityFilter(admin.SimpleListFilter):
    title = _('Total Quantity Zero')
    parameter_name = 'total_quantity_zero'

    def lookups(self, request, model_admin):
        return (
            ('yes', _('Yes')),
            ('no', _('No')),
        )

    def queryset(self, request, queryset):
        if self.value() == 'yes':
            return queryset.filter(total_quantity=0)
        if self.value() == 'no':
            return queryset.exclude(total_quantity=0)
        return queryset


class HasImageFilter(admin.SimpleListFilter):
    title = _('Has Image')
    parameter_name = 'has_image'

    def lookups(self, request, model_admin):
        return (
            ('yes', _('Yes')),
            ('no', _('No')),
        )

    def queryset(self, request, queryset):
        if self.value() == 'yes':
            return queryset.exclude(asset_img__isnull=True).exclude(asset_img__exact='')
        if self.value() == 'no':
            return queryset.filter(models.Q(asset_img__isnull=True) | models.Q(asset_img__exact=''))
        return queryset


class QuantityTypeFilter(admin.SimpleListFilter):
    title = _('Quantity Type')
    parameter_name = 'quantity_type'

    def lookups(self, request, model_admin):
        # Devuelve las opciones del filtro con las etiquetas legibles
        from apps.project.specific.assets_management.assets_location.models import AssetLocationModel
        return AssetLocationModel.QuantityTypeChoices.choices

    def queryset(self, request, queryset):
        # Filtra el queryset según el tipo seleccionado
        if self.value():
            return queryset.filter(
                assetlocation_assetlocation_asset__quantity_type=self.value()
            ).distinct()  # Asegurarse de que los registros no se dupliquen
        return queryset
