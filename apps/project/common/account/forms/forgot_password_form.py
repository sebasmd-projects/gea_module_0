# apps/project/common/account/forms.py


from django import forms
from django.utils.translation import gettext_lazy as _

from django.contrib.auth.forms import SetPasswordForm

from apps.project.common.users.models import UserModel

from django.core.exceptions import ValidationError
from apps.common.utils.functions import sha256_hex


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
        value = (self.cleaned_data.get(
            "email_or_username") or "").strip().lower()

        if not value:
            raise ValidationError(_("This field is required."))
        return value

    def get_user(self):
        raw = (self.cleaned_data.get('email_or_username') or '').strip()
        value = raw.casefold()

        if "@" in value:
            return UserModel.objects.filter(
                email_hash=sha256_hex(value.strip().lower())
            ).first()

        return UserModel.objects.filter(
            username__iexact=value
        ).first()


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
