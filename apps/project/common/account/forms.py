# apps/project/common/account/forms.py

import re

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.utils.translation import gettext_lazy as _
from django_select2 import forms as s2forms
from django.contrib.auth.forms import SetPasswordForm
from apps.common.utils.models import GeaDailyUniqueCode
from apps.project.common.users.models import UserModel
from apps.project.common.users.validators import (UnicodeLastNameValidator,
                                                  UnicodeNameValidator,
                                                  UnicodeUsernameValidator)
from django.core.exceptions import ValidationError

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
        label=_("Referred by"),
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


class ForgotPasswordStep1Form(forms.Form):
    """Step 1: Email/Username input for password reset request"""
    email_or_username = forms.CharField(
        label=_("Email or Username"),
        required=True,
        widget=forms.TextInput(attrs={
            "id": "forgot_email_username",
            "type": "text",
            "placeholder": _("Enter your email or username"),
            "class": "form-control",
            "autocomplete": "username",
        })
    )

    def clean_email_or_username(self):
        value = (self.cleaned_data.get("email_or_username") or "").strip().lower()

        if not value:
            raise ValidationError(_("This field is required."))
        return value

    def get_user(self):
        """Return user object based on cleaned data"""
        email_or_username = self.cleaned_data.get(
            'email_or_username', '').strip().lower()

        try:
            return UserModel.objects.get(email_hash=email_or_username)
        except UserModel.DoesNotExist:
            try:
                return UserModel.objects.get(username=email_or_username)
            except UserModel.DoesNotExist:
                return None


class ForgotPasswordStep2Form(SetPasswordForm):
    """Step 2: New password and confirmation"""
    new_password1 = forms.CharField(
        label=_("New password"),
        widget=forms.PasswordInput(attrs={
            "id": "new_password1",
            "type": "password",
            "placeholder": _("Enter new password"),
            "class": "form-control",
            "autocomplete": "new-password",
        }),
        strip=False,
    )
    new_password2 = forms.CharField(
        label=_("Confirm new password"),
        widget=forms.PasswordInput(attrs={
            "id": "new_password2",
            "type": "password",
            "placeholder": _("Confirm new password"),
            "class": "form-control",
            "autocomplete": "new-password",
        }),
        strip=False,
    )

    def __init__(self, user, *args, **kwargs):
        super().__init__(user, *args, **kwargs)
        self.fields['new_password1'].label = _("New Password")
        self.fields['new_password2'].label = _("Confirm New Password")


class ChangePasswordForm(forms.Form):
    """Change password form for logged-in users"""
    old_password = forms.CharField(
        label=_("Current Password"),
        widget=forms.PasswordInput(attrs={
            "id": "old_password",
            "type": "password",
            "placeholder": _("Enter your current password"),
            "class": "form-control",
            "autocomplete": "current-password",
        }),
        strip=False,
        required=True,
    )

    new_password1 = forms.CharField(
        label=_("New Password"),
        widget=forms.PasswordInput(attrs={
            "id": "new_password1",
            "type": "password",
            "placeholder": _("Enter new password"),
            "class": "form-control",
            "autocomplete": "new-password",
        }),
        strip=False,
        required=True,
    )

    new_password2 = forms.CharField(
        label=_("Confirm New Password"),
        widget=forms.PasswordInput(attrs={
            "id": "new_password2",
            "type": "password",
            "placeholder": _("Confirm new password"),
            "class": "form-control",
            "autocomplete": "new-password",
        }),
        strip=False,
        required=True,
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_old_password(self):
        old_password = self.cleaned_data.get("old_password")
        if not self.user.check_password(old_password):
            raise forms.ValidationError(
                _("Your current password was entered incorrectly."))
        return old_password

    def clean_new_password1(self):
        new_password1 = self.cleaned_data.get("new_password1")
        validate_password(new_password1, self.user)
        return new_password1

    def clean(self):
        cleaned_data = super().clean()
        new_password1 = cleaned_data.get("new_password1")
        new_password2 = cleaned_data.get("new_password2")

        if new_password1 and new_password2:
            if new_password1 != new_password2:
                self.add_error("new_password2", _(
                    "The two password fields didn't match."))

        # Check if new password is same as old password
        old_password = cleaned_data.get("old_password")
        if new_password1 and old_password and new_password1 == old_password:
            self.add_error("new_password1", _(
                "New password cannot be the same as current password."))

        return cleaned_data

    def save(self, commit=True):
        password = self.cleaned_data["new_password1"]
        self.user.set_password(password)
        if commit:
            self.user.save()
        return self.user
