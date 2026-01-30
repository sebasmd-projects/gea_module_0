# apps/project/common/account/forms/suppliers_register_form.py

from django import forms
from django.utils.translation import gettext_lazy as _

from .common_register_form import ContactBaseForm


class SupplierContactForm(ContactBaseForm):
    """
    Paso 3 para Intermediario/Representante/Tenedor:
    - email cualquier dominio
    - confirmación
    - no envía código por email
    """
    email = forms.EmailField(
        label=_("Email"),
        widget=forms.EmailInput(attrs={
            "id": "register_email",
            "type": "email",
            "placeholder": _("Email"),
            "class": "form-control",
        })
    )
    
    confirm_email = forms.EmailField(
        label=_("Confirm Email"),
        widget=forms.EmailInput(attrs={
            "id": "register_confirm_email",
            "type": "email",
            "placeholder": _("Confirm Email"),
            "class": "form-control",
        })
    )
    
    def clean_email(self):
        return (self.cleaned_data.get("email") or "").strip().lower()

    def clean_confirm_email(self):
        return (self.cleaned_data.get("confirm_email") or "").strip().lower()

    def clean(self):
        cleaned = super().clean()
        e1 = cleaned.get("email")
        e2 = cleaned.get("confirm_email")
        if e1 and e2 and e1 != e2:
            self.add_error("confirm_email", _("Emails do not match."))
        return cleaned
