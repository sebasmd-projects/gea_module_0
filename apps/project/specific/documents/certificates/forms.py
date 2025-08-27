import re

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import CertificateModel


class IDNumberForm(forms.Form):

    document_type = forms.ChoiceField(
        label=_("Document Type"),
        choices=CertificateModel.DocumentTypeChoices.choices,
        initial=CertificateModel.DocumentTypeChoices.CC
    )

    document_number = forms.CharField(
        label=_('Document Number'),
        max_length=64
    )
    
class IDNumberMinForm(forms.Form):

    document_type = forms.ChoiceField(
        label=_("Document Type"),
        choices=CertificateModel.DocumentTypeChoicesMin.choices,
        initial=CertificateModel.DocumentTypeChoicesMin.PA
    )

    document_number = forms.CharField(
        label=_('Document Number'),
        max_length=64
    )

