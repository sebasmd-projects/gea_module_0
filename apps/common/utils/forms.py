from django import forms
from django.utils.translation import gettext_lazy as _


class KeyForm(forms.Form):
    key = forms.CharField(
        max_length=6,
        required=False,
        label=_("Security Key")
    )
