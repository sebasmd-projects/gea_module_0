# apps/project/common/account/forms/common_register_form.py

import re

from django import forms
from django.utils.translation import gettext_lazy as _

from django_select2 import forms as s2forms

from apps.project.common.users.models import UserModel
from apps.project.common.users.validators import (UnicodeLastNameValidator,
                                                  UnicodeNameValidator,
                                                  UnicodeUsernameValidator)


class CommonCleanMixin:
    """Utilidades comunes para limpieza/normalización."""

    def clean_username(self):
        v = (self.cleaned_data.get("username") or "").strip()
        UnicodeUsernameValidator()(v)
        return v

    def clean_first_name(self):
        v = (self.cleaned_data.get("first_name") or "").strip()
        UnicodeNameValidator()(v)
        return v

    def clean_last_name(self):
        v = (self.cleaned_data.get("last_name") or "").strip()
        UnicodeLastNameValidator()(v)
        return v


class PhoneNumberCodeWidget(s2forms.Select2Widget):
    
    def build_attrs(self, base_attrs, extra_attrs=None):
        attrs = super().build_attrs(base_attrs, extra_attrs)
        attrs['data-minimum-input-length'] = 1
        attrs.update({
            'data-width': '100%',
            'style': 'width:100%;',
        })
        return attrs

class ReferredUserChoiceField(forms.ModelChoiceField):
        def label_from_instance(self, obj):
            return obj.get_full_name()
        
class UserInformationForm(CommonCleanMixin, forms.Form):
    """
    Paso 1: User information
    """
    
    username = forms.CharField(
        label=_("Username"),
        max_length=150,
        widget=forms.TextInput(attrs={
            "id": "register_username",
            "type": "text",
            "placeholder": _("Username"),
            "class": "form-control",
        })
    )

    first_name = forms.CharField(
        label=_("Names"),
        max_length=150,
        widget=forms.TextInput(attrs={
            "id": "register_first_name",
            "type": "text",
            "placeholder": _("Names"),
            "class": "form-control",
        })
    )

    last_name = forms.CharField(
        label=_("Surnames"),
        max_length=150,
        widget=forms.TextInput(attrs={
            "id": "register_last_name",
            "type": "text",
            "placeholder": _("Last names"),
            "class": "form-control",
        })
    )

    user_type = forms.ChoiceField(
        label=_("User type"),
        choices=UserModel.UserTypeChoices.choices,
        widget=forms.Select(attrs={
            "id": "register_user_type",
            "class": "form-select",
        })
    )

    referred = ReferredUserChoiceField(
        label=_("Referred by"),
        required=False,
        queryset=UserModel.objects.filter(is_referred=True),
        widget=forms.Select(attrs={
            "id": "register_referred",
            "class": "form-select",
        }),
    )

class SecurityInformationForm(forms.Form):
    """
    Paso 2: Security Information (aplica para ambos)
    """
    password = forms.CharField(
        label=_("Password"),
        widget=forms.PasswordInput(attrs={
            "id": "register_password",
            "type": "password",
            "placeholder": _("Password"),
            "class": "form-control",
        })
    )

    confirm_password = forms.CharField(
        label=_("Confirm Password"),
        widget=forms.PasswordInput(attrs={
            "id": "register_confirm_password",
            "type": "password",
            "placeholder": _("Confirm Password"),
            "class": "form-control",
        })
    )

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password")
        p2 = cleaned.get("confirm_password")
        if p1 and p2 and p1 != p2:
            self.add_error("confirm_password", _("Passwords do not match."))
        return cleaned


class ContactBaseForm(forms.Form):
    """
    Paso 3 (común): phone code + phone (email se especializa por tipo)
    """

    phone_number_code = forms.ChoiceField(
        label=_("Code"),
        choices=UserModel.PhoneCodeChoices.choices,
        widget=PhoneNumberCodeWidget(attrs={
            "id": "register_phone_number_code",
            "class": "form-select",
        })
    )


    phone_number = forms.CharField(
        label=_("Cell phone"),
        max_length=15,
        widget=forms.TextInput(attrs={
            "id": "register_phone_number",
            "type": "tel",
            "inputmode": "numeric",
            "pattern": r"\d{7,15}",
            "placeholder": _("Cellphone"),
            "class": "form-control",
            "maxlength": "25",
            "autocomplete": "tel",
        })
    )

    def clean_phone_number_code(self):
        return (self.cleaned_data.get("phone_number_code") or "").strip()

    def clean_phone_number(self):
        raw = (self.cleaned_data.get("phone_number") or "").strip()
        digits = re.sub(r"\D+", "", raw)
        if not (7 <= len(digits) <= 15):
            raise forms.ValidationError(
                _("Enter a valid phone number (7–15 digits)."))
        return digits


class UniqueCodeForm(forms.Form):
    """
    Paso 4: unique code
    """
    unique_code = forms.CharField(
        label=_("Unique code"),
        max_length=64,
        widget=forms.PasswordInput(attrs={
            "id": "register_unique_code",
            "type": "password",
            "placeholder": _("Unique Code"),
            "class": "form-control",
            "autocomplete": "one-time-code"
        })
    )
