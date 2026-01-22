from django import forms
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError

from .functions import is_temporary_email, is_ipcon_email
from .models import DocumentCertificateTypeChoices, DocumentTypeChoices


class CertificateUserForm(forms.Form):

    document_type = forms.ChoiceField(
        label=_("Document Type"),
        choices=DocumentTypeChoices.choices,
        initial=DocumentTypeChoices.PA
    )

    document_number = forms.CharField(
        label=_('Document Number'),
        max_length=64,
        widget=forms.TextInput(
            attrs={
                "placeholder": _("Enter document"),
            }
        )
    )

class DocumentVerificationForm(forms.Form):
    certificate_type = forms.ChoiceField(
        choices=DocumentCertificateTypeChoices.choices,
        label=_('Certificate type')
    )
    
    identifier = forms.CharField(
        label=_('Document Public Code'),
        max_length=36,
        widget=forms.TextInput(
            attrs={
                "placeholder": _("Enter public code, prefix or UUID"),
            }
        )
    )

    def clean_identifier(self):
        value = self.cleaned_data['identifier'].strip().upper()
        if len(value) not in (4, 8, 36):
            raise ValidationError(_('Invalid identifier length.'))
        return value


class AnonymousEmailOTPForm(forms.Form):
    email = forms.EmailField(
        label=_('Email'),
        widget=forms.EmailInput(
            attrs={
                "placeholder": _("Enter your email for OTP verification"),
            }
        )
    )

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        if is_temporary_email(email):
            raise ValidationError(_('Temporary email addresses are not allowed.'))
        
        if not is_ipcon_email(email):
            raise ValidationError(_('Only authorized emails.'))
        
        return email


class AnonymousOTPVerifyForm(forms.Form):
    otp = forms.CharField(
        label=_('Verification code'),
        max_length=6,
        widget=forms.TextInput(
            attrs={
                "placeholder": _("Enter the 6-digit code"),
                "inputmode": "numeric",
                "autocomplete": "one-time-code",
            }
        )
    )