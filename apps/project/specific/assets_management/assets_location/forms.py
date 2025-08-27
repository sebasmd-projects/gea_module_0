from django import forms
from django.utils.translation import gettext_lazy as _
from django_select2 import forms as s2forms

from .models import AssetLocationModel, LocationModel


class CountryWidget(s2forms.ModelSelect2Widget):
    search_fields = [
        "es_country_name__icontains",
        "en_country_name__icontains",
    ]

    def build_attrs(self, base_attrs, extra_attrs=None):
        attrs = super().build_attrs(base_attrs, extra_attrs)
        attrs['data-minimum-input-length'] = 2
        return attrs

class AssetWidget(s2forms.ModelSelect2Widget):
    search_fields = [
        "asset_name__es_name__icontains",
        "asset_name__en_name__icontains",
    ]

    def build_attrs(self, base_attrs, extra_attrs=None):
        attrs = super().build_attrs(base_attrs, extra_attrs)
        attrs['data-minimum-input-length'] = 0  # Sin longitud mínima para mostrar resultados
        return attrs
    


class LocationModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

    class Meta:
        model = LocationModel
        fields = ['reference', 'description_es', 'description_en','country']
        widgets = {
            "country": CountryWidget,
        }


class AssetLocationModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields['location'].queryset = LocationModel.objects.filter(
                created_by=user)
        self.fields['observations_es'].widget.attrs.update(
            {
                'placeholder': _('Enter any relevant notes or details here (Spanish)')
            }
        )
        self.fields['observations_en'].widget.attrs.update(
            {
                'placeholder': _('Enter any relevant notes or details here (English)')
            }
        )
        
    def clean(self):
        cleaned_data = super().clean()
        asset = cleaned_data.get('asset')
        location = cleaned_data.get('location')
        quantity_type = cleaned_data.get('quantity_type')
        amount = cleaned_data.get('amount')
        created_by = self.initial.get('user')

        # Verificar duplicados
        if AssetLocationModel.objects.filter(
            asset=asset,
            location=location,
            quantity_type=quantity_type,
            amount=amount,
            created_by=created_by,
        ).exists():
            raise forms.ValidationError(_("A similar asset location already exists."))

        return cleaned_data

    class Meta:
        model = AssetLocationModel
        fields = [
            'asset',
            'location',
            'quantity_type',
            'amount',
            'observations_es',
            'observations_en'
        ]
        widgets = {
            'asset': AssetWidget,
        }

class AssetUpdateLocationModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields['location'].queryset = LocationModel.objects.filter(
                created_by=user)
        self.fields['asset'].disabled = True
        self.fields['observations_es'].widget.attrs.update(
            {
                'placeholder': _('Enter any relevant notes or details here (Spanish)')
            }
        )
        self.fields['observations_en'].widget.attrs.update(
            {
                'placeholder': _('Enter any relevant notes or details here (English)')
            }
        )

    class Meta:
        model = AssetLocationModel
        fields = [
            'asset',
            'location',
            'quantity_type',
            'amount',
            'observations_es',
            'observations_en'
        ]
