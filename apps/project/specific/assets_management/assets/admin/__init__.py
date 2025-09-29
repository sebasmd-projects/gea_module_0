
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet
from django.utils.translation import gettext_lazy as _
from import_export import fields, resources
from import_export.admin import ImportExportModelAdmin
from import_export.formats.base_formats import CSV
from import_export.widgets import ForeignKeyWidget

from apps.common.utils.admin import GeneralAdminModel

from ..models import AssetCategoryModel, AssetModel, AssetsNamesModel
from .filters import HasImageFilter, QuantityTypeFilter


class AssetCategoryResource(resources.ModelResource):
    class Meta:
        model = AssetCategoryModel
        import_id_fields = ('id',)   # usamos el id del CSV
        fields = ('id', 'is_active', 'default_order',
                  'es_name', 'en_name', 'description')


class AssetsNamesResource(resources.ModelResource):
    class Meta:
        model = AssetsNamesModel
        import_id_fields = ('id',)   # usamos el id del CSV
        fields = ('id', 'is_active', 'default_order', 'es_name', 'en_name')


class AssetResource(resources.ModelResource):
    asset_name = fields.Field(attribute='asset_name', column_name='asset_id',
                              widget=ForeignKeyWidget(AssetsNamesModel, 'id'))
    category = fields.Field(attribute='category', column_name='category_id',
                            widget=ForeignKeyWidget(AssetCategoryModel, 'id'))

    class Meta:
        model = AssetModel
        fields = (
            'id',
            'is_active',
            'default_order',
            'asset_img',
            'asset_name',
            'category',
            'es_description',
            'en_description',
            'es_observations',
            'en_observations',
        )


class RequiredInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if not any(
            form.cleaned_data and not form.cleaned_data.get("DELETE", False)
            for form in self.forms
        ):
            raise ValidationError(_("You must add at least one asset."))


class AssetCategoryInline(admin.StackedInline):
    model = AssetModel  # Asume que AssetModel gestiona la relación con categoría
    fk_name = "asset_name"  # Indica el campo de ForeignKey que conecta con AssetsNamesModel
    extra = 1  # Define cuántos campos adicionales se mostrarán por defecto
    max_num = 1
    can_delete = False
    autocomplete_fields = ("category",)
    formset = RequiredInlineFormSet


@admin.register(AssetsNamesModel)
class AssetsNamesModelAdmin(ImportExportModelAdmin, GeneralAdminModel):
    
    def get_read_kwargs(self, encoding, **kwargs):
        params = super().get_read_kwargs(encoding, **kwargs)
        params["delimiter"] = ";"      # <- clave
        return params

    resource_classes = [AssetsNamesResource]

    inlines = [AssetCategoryInline]

    search_fields = (
        'es_name',
        'en_name'
    )

    list_display = (
        'es_name',
        'en_name',
        'created',
        'updated',
        'is_active',
    )

    list_display_links = (
        'es_name',
        'en_name'
    )

    readonly_fields = (
        'id',
        'created',
        'updated'
    )

    ordering = (
        'default_order',
        'created'
    )

    fieldsets = (
        (_('Details'), {
            'fields': (
                'id',
                'es_name',
                'en_name',
                'is_active',
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


@admin.register(AssetCategoryModel)
class AssetCategoryModelAdmin(ImportExportModelAdmin, GeneralAdminModel):

    resource_classes = [AssetCategoryResource]

    search_fields = (
        'en_name',
        'es_name'
    )

    list_filter = (
        'is_active',
    )

    list_display = (
        'en_name',
        'es_name',
        'created',
        'updated',
        'is_active'
    )

    list_display_links = list_display[:2]

    ordering = (
        'default_order',
        '-created'
    )

    readonly_fields = (
        'id',
        'created',
        'updated',
    )

    fieldsets = (
        (_('Details'), {
            'fields': (
                'id',
                'es_name',
                'en_name',
                'es_description',
                'en_description',
                'is_active',
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


@admin.register(AssetModel)
class AssetModelAdmin(ImportExportModelAdmin, GeneralAdminModel):

    resource_classes = [AssetResource]

    autocomplete_fields = (
        'asset_name',
        'category',
    )

    search_fields = (
        'id',
        'asset_name__es_name',
        'asset_name__en_name',

        'category__es_name',
        'category__en_name',
    )

    list_filter = (
        'is_active',
        QuantityTypeFilter,
        HasImageFilter,
        'category',
    )

    list_display = (
        'get_asset_es_name',
        'get_asset_en_name',
        'category',
        'get_asset_total_quantity_by_type',
        'es_observations',
        'en_observations',
        'es_description',
        'en_description',
        'is_active',
    )

    list_display_links = list_display[:3]

    readonly_fields = (
        'id',
        'created',
        'updated',
        'get_asset_total_quantity_by_type',
    )

    ordering = (
        'default_order',
        'created'
    )

    fieldsets = (
        (_('Required Fields'), {
            'fields':
                (
                    'id',
                    'asset_img',
                    'asset_name',
                    'category',
                    'is_active',
                    'get_asset_total_quantity_by_type',
                )
        }
        ),
        (_('Optional Fields'), {
            'fields': (
                'es_observations',
                'en_observations',
                'es_description',
                'en_description',
            ),
            'classes': (
                'collapse',
            )
        }
        ),
        (_('Dates'), {
            'fields': (
                'created',
                'updated'
            ),
            'classes': (
                'collapse',
            )
        }
        ),
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
        return obj.asset_name.es_name
    get_asset_es_name.short_description = _('Asset Name (ES)')

    def get_asset_en_name(self, obj):
        return obj.asset_name.en_name
    get_asset_en_name.short_description = _('Asset Name (EN)')

    def get_asset_total_quantity_by_type(self, obj):
        totals = obj.asset_total_quantity_by_type() or {}
        return ", ".join(f"{key}: {value}" for key, value in totals.items())
    
    get_asset_total_quantity_by_type.short_description = _(
        'Total Quantity by Type')
