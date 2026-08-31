# apps/project/specific/documents/certificates/forms.py

from django import forms
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.conf import settings

from .constants import (MAX_VERIFICATION_UPLOAD_BYTES,
                        VERIFICATION_UPLOAD_EXTENSIONS)
from .functions import is_temporary_email, is_ipcon_email, normalize_identifier
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
    """
    Un solo campo: el codigo.

    Habia un desplegable de tipo de certificado, y era obligatorio. Solo podia
    producir falsos negativos: el codigo publico es ``unique=True`` en toda la
    tabla, asi que el tipo no forma parte de la identidad -- como mucho acota
    una busqueda que ya devuelve un unico resultado. Quien tiene el papel
    delante no sabe si sostiene un "Asset Certificate (AEGIS)" o un "Generic
    Document", y elegir mal daba "Document not found" con un codigo
    perfectamente valido en la mano.

    Un campo que no puede mejorar el resultado y si puede estropearlo no es un
    filtro: es un paso de mas y una forma de equivocarse.
    """

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
        raw = self.cleaned_data["identifier"]
        try:
            return normalize_identifier(raw)
        except ValidationError as e:
            raise forms.ValidationError(e.message)


class DocumentFileVerificationForm(forms.Form):
    """
    Verificacion subiendo el propio archivo.

    No se guarda nada del archivo recibido: se calcula su huella en memoria y
    se descarta.
    """

    document_file = forms.FileField(
        label=_('Document file'),
        help_text=_(
            'Upload the PDF you want to verify: the original, the certified '
            'document or the distributable digital copy.'
        ),
        widget=forms.ClearableFileInput(
            attrs={
                'accept': ','.join(VERIFICATION_UPLOAD_EXTENSIONS),
            }
        )
    )

    def clean_document_file(self):
        uploaded = self.cleaned_data['document_file']

        name = (uploaded.name or '').lower()

        if not name.endswith(VERIFICATION_UPLOAD_EXTENSIONS):
            raise ValidationError(
                _('Only these formats can be verified: %(formats)s.')
                % {'formats': ', '.join(VERIFICATION_UPLOAD_EXTENSIONS)}
            )

        if uploaded.size > MAX_VERIFICATION_UPLOAD_BYTES:
            raise ValidationError(
                _('The file is too large. The maximum is %(size)s MB.')
                % {'size': MAX_VERIFICATION_UPLOAD_BYTES // (1024 * 1024)}
            )

        return uploaded


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
        email = (self.cleaned_data["email"] or "").strip().lower()

        if is_temporary_email(email):
            raise ValidationError(
                _('Temporary email addresses are not allowed.'))

        if not is_ipcon_email(email, getattr(settings, "ALLOW_ANY_EMAIL_IPCON", False)):
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
