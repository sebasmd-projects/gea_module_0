from django import forms
from django.utils.translation import gettext_lazy as _, get_language
from django_select2 import forms as s2forms

from .models import AssetModel, PreRegistrationAssetModel


class AssetNameWidget(s2forms.ModelSelect2Widget):
    search_fields = [
        "es_name__icontains",
        "en_name__icontains",
    ]

    def build_attrs(self, base_attrs, extra_attrs=None):
        attrs = super().build_attrs(base_attrs, extra_attrs)
        attrs['data-minimum-input-length'] = 0
        return attrs
    
    def label_from_instance(self, obj):
        lang = get_language()
        if lang == "es" and getattr(obj, "es_name", None):
            return obj.es_name
        # Fallback a EN si hay, si no a ES
        return getattr(obj, "en_name", None) or getattr(obj, "es_name", "")


class AssetCategoryWidget(s2forms.ModelSelect2Widget):
    search_fields = [
        "es_name__icontains",
        "en_name__icontains",
    ]

    def build_attrs(self, base_attrs, extra_attrs=None):
        attrs = super().build_attrs(base_attrs, extra_attrs)
        attrs['data-minimum-input-length'] = 0
        return attrs
    
    def label_from_instance(self, obj):
        lang = get_language()
        if lang == "es" and getattr(obj, "es_name", None):
            return obj.es_name
        return getattr(obj, "en_name", None) or getattr(obj, "es_name", "")


class AssetModelForm(forms.ModelForm):
    class Meta:
        model = AssetModel
        fields = [
            'asset_img',
            'asset_name',
            'category',
            'description',
            'observations',
        ]
        widgets = {
            'asset_name': AssetNameWidget,
            'category': AssetCategoryWidget,
        }


class PreRegistrationAssetForm(forms.ModelForm):

    class Meta:
        model = PreRegistrationAssetModel
        fields = [
            'has_item',
            'es_observations',
            'en_observations'
        ]
        widgets = {
            'has_item': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'es_observations': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Observaciones'}),
            'en_observations': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Observations'}),
        }
