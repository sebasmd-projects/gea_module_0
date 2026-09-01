# apps/project/common/pqrs/forms.py
"""
Los cinco pasos del formulario de PQRS.

Se parte en pasos porque el formulario entero es largo y **cambia de forma**:
una persona juridica pide razon social, NIT, representante legal y certificado
de existencia; una natural, nombres, apellidos y documento. Enseñar los dos
juegos de campos a la vez y esconder la mitad con JavaScript deja el
formulario dependiendo del navegador para validar, que es donde se cuelan los
datos incompletos.

Aqui la rama se decide en el servidor: el paso 2 sirve un formulario u otro
segun lo que se eligio en el paso 1, y el que no toca ni se envia ni se
valida.
"""

import os

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import PQRSRequest, RequestTypeChoices

#: Lo que se admite como soporte de identidad.
#:
#: Es una lista de permitidos, no de prohibidos: lo que no se reconoce no
#: entra. Sin ella, este formulario --publico, sin sesion y con dos campos de
#: fichero-- acepta cualquier cosa de cualquier tamano, y la guarda.
ALLOWED_UPLOAD_EXTENSIONS = ('.pdf', '.jpg', '.jpeg', '.png', '.webp')

#: Un documento de identidad fotografiado no pasa de aqui. El tope existe
#: tanto por el disco --que en cPanel es una cuota fija-- como porque subir
#: ficheros enormes en bucle es la forma barata de llenarlo.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class SupportingDocumentField(forms.FileField):
    """
    Un adjunto con su tipo y su tamano comprobados.

    Va en una clase y no en un ``clean_<campo>`` por formulario porque son dos
    campos en dos formularios distintos, y la validacion que se escribe dos
    veces es la que acaba existiendo una.
    """

    def clean(self, data, initial=None):
        uploaded = super().clean(data, initial)

        if not uploaded:
            return uploaded

        extension = os.path.splitext(uploaded.name or '')[1].lower()

        if extension not in ALLOWED_UPLOAD_EXTENSIONS:
            raise forms.ValidationError(
                _('Only these formats are accepted: %(formats)s.')
                % {'formats': ', '.join(ALLOWED_UPLOAD_EXTENSIONS)}
            )

        if (uploaded.size or 0) > MAX_UPLOAD_BYTES:
            raise forms.ValidationError(
                _('The file is too large. The maximum is %(size)s MB.')
                % {'size': MAX_UPLOAD_BYTES // (1024 * 1024)}
            )

        return uploaded


class RequestTypeForm(forms.Form):
    """Paso 1. Decide el plazo legal, asi que va primero y va solo."""

    request_type = forms.ChoiceField(
        label=_('Type of request'),
        choices=RequestTypeChoices.choices,
        widget=forms.RadioSelect,
        help_text=_(
            'Access and query are answered within 10 business days. The rest '
            'are handled as claims, within 15.'
        ),
    )

    person_type = forms.ChoiceField(
        label=_('Who is filing it'),
        choices=PQRSRequest.PersonTypeChoices.choices,
        widget=forms.RadioSelect,
        initial=PQRSRequest.PersonTypeChoices.NATURAL,
    )


class HolderBaseForm(forms.Form):
    """Lo que se pide igual a las dos, para no escribirlo dos veces."""

    identification_type = forms.ChoiceField(
        label=_('Identification type'),
        choices=[('', _('-- Select one --'))] + list(
            PQRSRequest.IdentificationTypeChoices.choices),
    )
    identification_number = forms.CharField(
        label=_('Identification number'), max_length=50)

    country = forms.CharField(label=_('Country'), max_length=100)
    city = forms.CharField(label=_('City'), max_length=100)
    address = forms.CharField(label=_('Address'), max_length=255)

    email = forms.EmailField(label=_('Email address'))
    confirm_email = forms.EmailField(label=_('Confirm email address'))

    phone_code = forms.CharField(
        label=_('Code'), max_length=7, initial='+57')
    phone_number = forms.CharField(label=_('Mobile'), max_length=25)

    def clean_email(self):
        return (self.cleaned_data.get('email') or '').strip().lower()

    def clean_confirm_email(self):
        return (self.cleaned_data.get('confirm_email') or '').strip().lower()

    def clean(self):
        cleaned = super().clean()

        first = cleaned.get('email')
        second = cleaned.get('confirm_email')

        # Se pide dos veces porque **es la unica via de respuesta**. Un
        # digito mal en el correo no da error: la solicitud se tramita, se
        # contesta dentro de plazo, y la respuesta se pierde.
        if first and second and first != second:
            self.add_error('confirm_email', _('The emails do not match.'))

        return cleaned


class NaturalHolderForm(HolderBaseForm):
    """Paso 2, persona natural."""

    first_name = forms.CharField(label=_('Names'), max_length=150)
    last_name = forms.CharField(label=_('Surnames'), max_length=150)

    identity_document = SupportingDocumentField(
        label=_('Identity document'),
        required=False,
        help_text=_(
            'Optional, but it speeds things up: we have to be sure who is '
            'asking before handing over or changing personal data.'
        ),
    )

    field_order = [
        'first_name', 'last_name',
        'identification_type', 'identification_number',
        'country', 'city', 'address',
        'email', 'confirm_email', 'phone_code', 'phone_number',
        'identity_document',
    ]


class LegalHolderForm(HolderBaseForm):
    """Paso 2, persona juridica."""

    company_name = forms.CharField(
        label=_('Company name'), max_length=200)
    legal_representative = forms.CharField(
        label=_('Legal representative'), max_length=200)

    legal_existence_document = SupportingDocumentField(
        label=_('Certificate of existence and legal representation'),
        required=False,
        help_text=_(
            'It is what shows the representative can act for the company.'
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Una persona juridica se identifica por NIT; ofrecer cedula aqui es
        # invitar a mezclar el documento del representante con el de la
        # empresa, y luego no se sabe a nombre de quien va la solicitud.
        self.fields['identification_type'].choices = [
            (PQRSRequest.IdentificationTypeChoices.NIT,
             PQRSRequest.IdentificationTypeChoices.NIT.label),
        ]
        self.fields['identification_type'].initial = (
            PQRSRequest.IdentificationTypeChoices.NIT)
        self.fields['identification_number'].label = _('NIT')

    field_order = [
        'company_name', 'identification_type', 'identification_number',
        'legal_representative',
        'country', 'city', 'address',
        'email', 'confirm_email', 'phone_code', 'phone_number',
        'legal_existence_document',
    ]


class DescriptionForm(forms.Form):
    """Paso 3."""

    description = forms.CharField(
        label=_('Description of the request'),
        widget=forms.Textarea(attrs={'rows': 8}),
        min_length=20,
        max_length=5000,
        help_text=_(
            'Say what happened and what you are asking for. If it is about a '
            'specific record, quoting its reference saves a round trip.'
        ),
    )

    def clean_description(self):
        return (self.cleaned_data.get('description') or '').strip()


class ContactForm(forms.Form):
    """Paso 4. Por defecto se responde a los datos del paso 2."""

    use_titular_contact = forms.BooleanField(
        label=_('Use the contact details I gave above'),
        required=False,
        initial=True,
    )

    contact_email = forms.EmailField(
        label=_('Contact email'), required=False)
    contact_phone = forms.CharField(
        label=_('Contact mobile'), max_length=25, required=False)
    contact_landline = forms.CharField(
        label=_('Landline'), max_length=25, required=False)

    def clean(self):
        cleaned = super().clean()

        if cleaned.get('use_titular_contact'):
            return cleaned

        alternatives = (
            cleaned.get('contact_email'),
            cleaned.get('contact_phone'),
            cleaned.get('contact_landline'),
        )

        if not any(alternatives):
            self.add_error(
                'contact_email',
                _('Give at least one way to reach you, or tick the box '
                  'above.'),
            )

        return cleaned


class ConfirmationForm(forms.Form):
    """
    Paso 5. Sin este visto bueno no hay autorizacion, y sin autorizacion no
    se puede tratar el dato (Ley 1581, art. 9).
    """

    accepted_terms = forms.BooleanField(
        label=_('I accept the personal data processing policy'),
        required=True,
        error_messages={
            'required': _(
                'Without accepting the policy we cannot process the request: '
                'handling your data needs your authorisation.'
            ),
        },
    )
