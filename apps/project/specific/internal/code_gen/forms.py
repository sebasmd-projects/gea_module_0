from django import forms
from django.utils.translation import gettext_lazy as _
from .models import CodeRegistrationModel


class CodeForm(forms.ModelForm):
    include_nit = forms.BooleanField(
        label=_("Include NIT"),
        required=False
    )
    include_date = forms.BooleanField(
        label=_("Include Date (DDMMYYYY)"),
        required=False
    )
    include_random_code = forms.BooleanField(
        label=_("Include Random Code (4 digits)"),
        required=False
    )
    include_f991 = forms.BooleanField(
        label="F991",
        required=False
    )
    include_m9q0 = forms.BooleanField(
        label="M9Q0",
        required=False
    )
    generate_qr_code = forms.BooleanField(
        label=_("Generate QR Code"),
        required=False
    )
    qr_image_url = forms.URLField(
        label=_("QR Image URL"),
        required=False,
        widget=forms.URLInput(
            attrs={
                'class': 'form-control',
                'placeholder': _('QR Image URL')
            }
        )
    )
    generate_barcode = forms.BooleanField(
        label=_("Generate Barcode"),
        required=False
    )

    class Meta:
        model = CodeRegistrationModel
        fields = [
            'reference',
            'description',
            'custom_text_input'
        ]
        widgets = {
            'reference': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': _('Reference'),
                    'required': True
                }
            ),
            'description': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'placeholder': _('Description')
                }
            ),
            'custom_text_input': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': _('Custom Text'),
                    'required': True
                }
            )
        }
