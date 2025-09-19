import re

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.utils.translation import gettext_lazy as _
from django_select2 import forms as s2forms

from apps.common.utils.models import GeaDailyUniqueCode
from apps.project.common.users.models import UserModel
from apps.project.common.users.validators import (UnicodeLastNameValidator,
                                                  UnicodeNameValidator,
                                                  UnicodeUsernameValidator)

USER_TXT = _('User')
EMAIL_TXT = _('Email')
PASSWORD_TXT = _('Password')


class PhoneNumberCodeWidget(s2forms.Select2Widget):
    def build_attrs(self, base_attrs, extra_attrs=None):
        attrs = super().build_attrs(base_attrs, extra_attrs)
        attrs['data-minimum-input-length'] = 1
        attrs.update({
            'data-width': '100%',     # Select2 usará 100%
            'style': 'width:100%;',   # fallback para 'width:style'
        })
        return attrs


class BaseUserForm(forms.ModelForm):
    username = forms.CharField(
        label=USER_TXT,
        validators=[UnicodeUsernameValidator()],
        required=True,
        widget=forms.TextInput(attrs={
            "id": "register_username",
            "type": "text",
            "placeholder": USER_TXT,
            "class": "form-control",
        })
    )
    email = forms.EmailField(
        label=EMAIL_TXT,
        required=True,
        widget=forms.EmailInput(attrs={
            "id": "register_email",
            "type": "email",
            "placeholder": EMAIL_TXT,
            "class": "form-control",
        })
    )
    password = forms.CharField(
        label=PASSWORD_TXT,
        required=True,
        widget=forms.PasswordInput(attrs={
            "id": "register_password",
            "type": "password",
            "placeholder": PASSWORD_TXT,
            "class": "form-control",
        })
    )
    confirm_password = forms.CharField(
        label=_("Confirm Password"),
        required=True,
        widget=forms.PasswordInput(attrs={
            "id": "register_confirm_password",
            "type": "password",
            "placeholder": _("Confirm Password"),
            "class": "form-control",
        })
    )
    first_name = forms.CharField(
        label=_("Names"),
        validators=[UnicodeNameValidator()],
        required=True,
        widget=forms.TextInput(attrs={
            "id": "register_first_name",
            "type": "text",
            "placeholder": _("Names"),
            "class": "form-control",
        })
    )
    last_name = forms.CharField(
        label=_("Last names"),
        validators=[UnicodeLastNameValidator()],
        required=True,
        widget=forms.TextInput(attrs={
            "id": "register_last_name",
            "type": "text",
            "placeholder": _("Last names"),
            "class": "form-control",
        })
    )
    unique_code = forms.CharField(
        label=_("Unique Code"),
        required=True,
        widget=forms.PasswordInput(attrs={
            "id": "register_unique_code",
            "type": "password",
            "placeholder": _("Unique Code"),
            "class": "form-control",
            "autocomplete": "one-time-code"
        })
    )
    phone_number = forms.CharField(
        label=_("Cellphone"),
        required=True,
        help_text=_("Digits only, 7–15 digits."),
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

    class Meta:
        model = UserModel
        fields = (
            "username", "email", "first_name", "last_name",
            "phone_number_code", "phone_number"
        )
        widgets = {
            "phone_number_code": PhoneNumberCodeWidget,
        }

    # Normaliza/valida el número (solo dígitos, 7–15)
    def clean_phone_number(self):
        raw = (self.cleaned_data.get("phone_number") or "").strip()
        digits = re.sub(r"\D+", "", raw)
        if not (7 <= len(digits) <= 15):
            raise forms.ValidationError(
                _("Enter a valid phone number (7–15 digits)."))
        return digits  # guardamos solo dígitos; el code va aparte


class GeaUserRegisterForm(BaseUserForm):
    user_type = forms.ChoiceField(
        label=_("User Type"),
        required=True,
        choices=UserModel.UserTypeChoices.choices,
        widget=forms.Select(attrs={
            "id": "register_user_type",
            "class": "form-select",
        })
    )
    
    referred = forms.ModelChoiceField(
        label=_("How did you hear about us?"),
        required=False,
        queryset=UserModel.objects.filter(is_referred=True),
        widget=forms.Select(attrs={
            "id": "register_referred",
            "class": "form-select",
        })
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['referred'].label_from_instance = lambda obj: obj.get_full_name()

    def clean(self):
        cleaned = super().clean()

        # Validar password / confirm
        password = cleaned.get("password")
        confirm_password = cleaned.get("confirm_password")
        if password and confirm_password:
            validate_password(password)
            if password != confirm_password:
                self.add_error("confirm_password", _("Passwords do not match"))

        # === Validar código según tipo de usuario ===
        user_type = cleaned.get("user_type")
        candidate = cleaned.get("unique_code")

        # Mapear tipo de usuario -> kind del código
        if user_type == UserModel.UserTypeChoices.BUYER:  # "B" comprador
            kind = GeaDailyUniqueCode.KindChoices.BUYER
        else:
            kind = GeaDailyUniqueCode.KindChoices.GENERAL

        if not GeaDailyUniqueCode.objects.verify_code(candidate, kind=kind):
            # Mensaje claro indicando a qué código pertenece la validación
            label = dict(GeaDailyUniqueCode.KindChoices.choices)[kind]
            self.add_error("unique_code", _(
                "Invalid Unique Code ({label})").format(label=label))

        return cleaned

    class Meta(BaseUserForm.Meta):
        fields = BaseUserForm.Meta.fields + ("user_type",)


class PropensionesUserRegisterForm(BaseUserForm):
    citizenship_number = forms.CharField(
        label=_("Citizenship Number"),
        required=False,
        widget=forms.TextInput(
            attrs={
                "id": "register_citizenship_number",
                "type": "text",
                "placeholder": _("Citizenship Number"),
                "class": "form-control",
            }
        )
    )

    class Meta(BaseUserForm.Meta):
        fields = BaseUserForm.Meta.fields + ("citizenship_number",)
