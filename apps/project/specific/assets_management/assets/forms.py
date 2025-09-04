from django import forms
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _
from django_select2 import forms as s2forms

from .models import AssetCategoryModel, AssetModel, AssetsNamesModel


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
            'es_description',
            'en_description',
            'es_observations',
            'en_observations',
        ]
        widgets = {
            'asset_name': AssetNameWidget,
            'category': AssetCategoryWidget,
        }


class AssetNameInlineForm(forms.ModelForm):
    class Meta:
        model = AssetsNamesModel
        fields = ("es_name", "en_name",)
        labels = {
            "es_name": _("Asset name (ES)"),
            "en_name": _("Asset name (EN)"),
        }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)

        lang = getattr(self.request, "LANGUAGE_CODE", "en")
        if lang == "es":
            # Mostramos solo ES
            self.fields["en_name"].widget = forms.HiddenInput()
            self.fields["es_name"].required = True
            self.fields["en_name"].required = False
        else:
            # Mostramos solo EN
            self.fields["es_name"].widget = forms.HiddenInput()
            self.fields["en_name"].required = True
            self.fields["es_name"].required = False

    def clean(self):
        cleaned = super().clean()
        es = (cleaned.get("es_name") or "").strip()
        en = (cleaned.get("en_name") or "").strip()

        lang = getattr(self.request, "LANGUAGE_CODE", "en")
        # Si uno falta, lo rellenamos con el otro
        if lang == "es":
            if not en and es:
                cleaned["en_name"] = es
        else:
            if not es and en:
                cleaned["es_name"] = en

        # Asegurar ambos
        if not cleaned.get("es_name") or not cleaned.get("en_name"):
            raise forms.ValidationError(
                _("Both ES and EN names must be set (we auto-fill the hidden one)."))

        return cleaned


class AssetInlineForm(forms.ModelForm):

    """
    Inline para registrar el Asset recién creado.
    NO expone asset_name (lo setea la vista).
    """
    class Meta:
        model = AssetModel
        fields = (
            "asset_img",
            "category",
            "es_description",
            "en_description",
            "es_observations",
            "en_observations",
        )
        widgets = {
            'category': AssetCategoryWidget,
            'es_description': forms.Textarea(attrs={"rows": 2}),
            'en_description': forms.Textarea(attrs={"rows": 2}),
            'es_observations': forms.Textarea(attrs={"rows": 2}),
            'en_observations': forms.Textarea(attrs={"rows": 2}),
        }


class AssetAddNewCategoryForm(forms.ModelForm):
    class Meta:
        model = AssetCategoryModel
        fields = ["es_name", "en_name", "es_description", "en_description"]
