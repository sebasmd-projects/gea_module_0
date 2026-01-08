import re

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import CertificateUserModel


class IDNumberForm(forms.Form):

    document_type = forms.ChoiceField(
        label=_("Document Type"),
        choices=CertificateUserModel.DocumentTypeChoices.choices,
        initial=CertificateUserModel.DocumentTypeChoices.CC
    )

    document_number = forms.CharField(
        label=_('Document Number'),
        max_length=64
    )
    
class IDNumberMinForm(forms.Form):

    document_type = forms.ChoiceField(
        label=_("Document Type"),
        choices=CertificateUserModel.DocumentTypeChoices.choices,
        initial=CertificateUserModel.DocumentTypeChoices.PA
    )

    document_number = forms.CharField(
        label=_('Document Number'),
        max_length=64
    )

