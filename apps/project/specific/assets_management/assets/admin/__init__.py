
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet
from django.utils.formats import number_format
from django.utils.translation import gettext_lazy as _
from import_export import fields, resources
from import_export.admin import ImportExportModelAdmin
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


class RequiredInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if not any(
            form.cleaned_data and not form.cleaned_data.get("DELETE", False)
            for form in self.forms
        ):
            raise ValidationError(_("You must add at least one asset."))


class AssetResource(resources.ModelResource):
    # Campos “virtuales” para exportar nombres y categorías
    asset_name_es = fields.Field(column_name='nombre_es')
    asset_name_en = fields.Field(column_name='nombre_en')
    category_es = fields.Field(column_name='categoria_es')
    category_en = fields.Field(column_name='categoria_en')

    # Reexpone descripciones/observaciones asegurando string vacío si son None
    es_description = fields.Field(column_name='es_description')
    en_description = fields.Field(column_name='en_description')
    es_observations = fields.Field(column_name='es_observations')
    en_observations = fields.Field(column_name='en_observations')
    
    # --- cantidades ---
    qty_boxes  = fields.Field(column_name='cajas')
    qty_units  = fields.Field(column_name='unidades')

    class Meta:
        model = AssetModel
        # No incluimos 'id' ni los ForeignKey crudos
        fields = (
            'is_active',
            'default_order',
            # los 4 campos “virtuales”
            'asset_name_es',
            'asset_name_en',
            
            'qty_boxes',
            'qty_units',
            
            'category_es',
            'category_en',
            # textos
            'es_description',
            'en_description',
            'es_observations',
            'en_observations',
        )
        export_order = (
            'asset_name_es',
            'asset_name_en',
            'qty_boxes',
            'qty_units',
            'category_es',
            'category_en',
            'es_description',
            'en_description',
            'es_observations',
            'en_observations',
            'is_active',
            'default_order',
            
        )

    # ---- Dehydrate: cómo obtener el valor para cada columna “virtual” ----
    def dehydrate_asset_name_es(self, obj):
        return getattr(obj.asset_name, 'es_name', '') or ''

    def dehydrate_asset_name_en(self, obj):
        return getattr(obj.asset_name, 'en_name', '') or ''

    def dehydrate_category_es(self, obj):
        return getattr(obj.category, 'es_name', '') or ''

    def dehydrate_category_en(self, obj):
        return getattr(obj.category, 'en_name', '') or ''

    # Asegurar cadenas vacías en lugar de None para textos
    def dehydrate_es_description(self, obj):
        return obj.es_description or ''

    def dehydrate_en_description(self, obj):
        return obj.en_description or ''

    def dehydrate_es_observations(self, obj):
        return obj.es_observations or ''

    def dehydrate_en_observations(self, obj):
        return obj.en_observations or ''
    
    # ----- Dehydrate: cantidades -----
    @staticmethod
    def _get_totals(obj):
        """
        Se espera que obj.asset_total_quantity_by_type() retorne un dict tipo:
        {'Unidad': 12, 'Caja': 3} (clave/valor pueden variar en mayúsculas/plurales/inglés).
        """
        return (getattr(obj, 'asset_total_quantity_by_type', None) or (lambda: {}))() or {}
    
    @staticmethod
    def _safe_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
        
    @classmethod
    def _find_value_by_candidates(cls, totals, candidates):
        """
        Busca en `totals` por claves que coincidan con cualquiera en `candidates`
        (insensible a mayúsculas y espacios). Devuelve el valor o 0 si no existe.
        """
        # normalizamos claves del dict una vez
        normalized = {str(k).strip().lower(): v for k, v in totals.items()}
        for cand in candidates:
            if cand in normalized:
                return cls._safe_int(normalized[cand])
        return 0
        
    # ---------- Dehydrate: cantidades separadas ----------
    def dehydrate_qty_boxes(self, obj):
        totals = self._get_totals(obj)
        # Soporta español/inglés y singular/plural
        candidates = {'caja', 'cajas', 'box', 'boxes'}
        return self._find_value_by_candidates(totals, candidates)

    def dehydrate_qty_units(self, obj):
        totals = self._get_totals(obj)
        candidates = {'unidad', 'unidades', 'unit', 'units'}
        return self._find_value_by_candidates(totals, candidates)
   

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

    def _fmt_int(self, value):
        return number_format(value, use_l10n=True, force_grouping=True)

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
        partes = []
        for key, value in totals.items():
            try:
                partes.append(f"{key}: {self._fmt_int(int(value))}")
            except (TypeError, ValueError):
                partes.append(f"{key}: {value}")
        return ", ".join(partes)

    get_asset_total_quantity_by_type.short_description = _(
        'Total Quantity by Type')

    def default_order_fmt(self, obj):
        return self._fmt_int(obj.default_order)

    default_order_fmt.short_description = _('Priority')
    default_order_fmt.admin_order_field = 'default_order'
