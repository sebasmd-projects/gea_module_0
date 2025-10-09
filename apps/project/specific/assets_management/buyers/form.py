from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils.translation import get_language
from django_select2 import forms as s2forms

from apps.project.specific.assets_management.assets.models import AssetModel

from .models import OfferModel, ServiceOrderRecipient

UserModel = get_user_model()


class AssetNameWidget(s2forms.ModelSelect2Widget):
    # Importante: traversar la relación hacia AssetsNamesModel
    search_fields = [
        "asset_name__es_name__icontains",
        "asset_name__en_name__icontains",
        "category__es_name__icontains",
        "category__en_name__icontains",
    ]

    def build_attrs(self, base_attrs, extra_attrs=None):
        attrs = super().build_attrs(base_attrs, extra_attrs)
        attrs['data-minimum-input-length'] = 0
        return attrs

    def label_from_instance(self, obj: AssetModel):
        lang = get_language()
        es = getattr(obj.asset_name, "es_name", None)
        en = getattr(obj.asset_name, "en_name", None)
        if lang == "es" and es:
            return es
        return en or es or str(obj.asset_name)

    def get_queryset(self):
        qs = AssetModel.objects.filter(
            is_active=True).select_related("asset_name", "category")
        return qs


class CountryWidget(s2forms.ModelSelect2Widget):
    # Asegúrate que estos campos EXISTAN en AssetCountryModel.
    # Si tus nombres reales son distintos, cámbialos aquí.
    search_fields = [
        "es_country_name__icontains",
        "en_country_name__icontains",
    ]

    def build_attrs(self, base_attrs, extra_attrs=None):
        attrs = super().build_attrs(base_attrs, extra_attrs)
        attrs['data-minimum-input-length'] = 0
        return attrs

    def label_from_instance(self, obj):
        lang = get_language()
        es_name = getattr(obj, "es_country_name", None) or getattr(
            obj, "es_name", None)
        en_name = getattr(obj, "en_country_name", None) or getattr(
            obj, "en_name", None)
        if lang == "es" and es_name:
            return es_name
        return en_name or es_name or ""


class OfferForm(forms.ModelForm):
    class Meta:
        model = OfferModel
        fields = [
            'asset',
            'offer_type',
            'quantity_type',
            'offer_quantity',
            'en_observation',
            'es_observation',
            'en_description',
            'es_description',
            'buyer_country',
            'offer_img',
        ]
        widgets = {
            "buyer_country": CountryWidget,
            "asset": AssetNameWidget,
        }

    # Forzamos queryset del campo para que el widget lo herede
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['asset'].queryset = AssetModel.objects.filter(
            is_active=True).select_related("asset_name", "category")

        if not self.instance.pk:  # Solo en creación, no en edición
            try:
                colombia = self.fields['buyer_country'].queryset.get(
                    es_country_name__iexact="Colombia")
                self.fields['buyer_country'].initial = colombia.pk
            except Exception:
                pass


class OfferUpdateForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['asset'].disabled = True
        self.fields['offer_type'].disabled = True
        self.fields['asset'].queryset = AssetModel.objects.filter(
            is_active=True).select_related("asset_name", "category")

    class Meta:
        model = OfferModel
        fields = [
            'asset',
            'offer_type',
            'quantity_type',
            'offer_quantity',
            'en_observation',
            'es_observation',
            'en_description',
            'es_description',
            'buyer_country',
        ]
        widgets = {
            "buyer_country": CountryWidget,
        }


class ServiceOrderRecipientsForm(forms.Form):
    users = forms.ModelMultipleChoiceField(
        queryset=UserModel.objects.filter(is_active=True),
        required=False
    )
    user_types = forms.MultipleChoiceField(
        choices=UserModel.UserTypeChoices.choices,
        required=False
    )

    def save(self, offer, added_by):
        objs = []
        for u in self.cleaned_data.get("users") or []:
            objs.append(ServiceOrderRecipient(offer=offer, user=u, added_by=added_by))
        for ut in self.cleaned_data.get("user_types") or []:
            objs.append(ServiceOrderRecipient(offer=offer, user_type=ut, added_by=added_by))
        if objs:
            ServiceOrderRecipient.objects.bulk_create(objs, ignore_conflicts=True)
