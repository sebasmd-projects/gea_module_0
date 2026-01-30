
from django import forms
from django.contrib.auth.password_validation import validate_password
from django.utils.translation import gettext_lazy as _

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
