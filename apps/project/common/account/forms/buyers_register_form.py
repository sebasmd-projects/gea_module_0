# apps/project/common/account/forms/buyers_register_form.py

from django import forms
from django.utils.translation import gettext_lazy as _

from .common_register_form import ContactBaseForm


class BuyerContactForm(ContactBaseForm):
    """
    Paso 3 para Compra:
    - email solo dominios permitidos
    - confirmación
    - la acción de envío del código se ejecuta en la vista wizard
    """
    
    allowed_domains = {
        "@propensionesabogados.com",
        "@bradbauhof.com",
        "@bauhoflegal.com",
        "@gyllton.com",
        "@recoveryrepatriationfoundation.com",
    }

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
        v = (self.cleaned_data.get("email") or "").strip().lower()
        if not any(v.endswith(d) for d in self.allowed_domains):
            raise forms.ValidationError(
                _("Email domain is not allowed for buyer registration."))
        return v

    def clean_confirm_email(self):
        return (self.cleaned_data.get("confirm_email") or "").strip().lower()

    def clean(self):
        cleaned = super().clean()
        e1 = cleaned.get("email")
        e2 = cleaned.get("confirm_email")
        if e1 and e2 and e1 != e2:
            self.add_error("confirm_email", _("Emails do not match."))
        return cleaned
