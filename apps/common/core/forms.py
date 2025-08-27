import uuid

from django import forms
from django.utils.translation import gettext_lazy as _
from django_recaptcha.fields import ReCaptchaField

from apps.common.core.models import ContactModel
from apps.project.common.users.validators import (UnicodeLastNameValidator,
                                                  UnicodeNameValidator)


class ContactForm(forms.ModelForm):
    FIRST_NAME_TXT = _('First name')
    LAST_NAME_TXT = _('Last name')
    EMAIL_TXT = _('Your Email')
    SUBJECT_TXT = _('Subject')
    MESSAGE_TXT = _('Message')
    UNIQUE_ID_INITIAL_VALUE = uuid.uuid4()
    
    last_name_validator = UnicodeLastNameValidator()
    name_validator = UnicodeNameValidator()

    name = forms.CharField(
        label=FIRST_NAME_TXT,
        required=True,
        validators=[name_validator],
        widget=forms.TextInput(
            attrs={
                "id": "contact_first_name",
                "name": "contact_first_name",
                "type": "text",
                "placeholder": FIRST_NAME_TXT,
                "class": "form-control",
                'aria-label': FIRST_NAME_TXT,
                'aria-describedby': 'contact_first_name'
            }
        )
    )

    last_name = forms.CharField(
        label=LAST_NAME_TXT,
        required=True,
        validators=[last_name_validator],
        widget=forms.TextInput(
            attrs={
                "id": "contact_last_name",
                "name": "contact_last_name",
                "type": "text",
                "placeholder": LAST_NAME_TXT,
                "class": "form-control",
                'aria-label': LAST_NAME_TXT,
                'aria-describedby': 'contact_last_name'
            }
        )
    )

    subject = forms.CharField(
        label=SUBJECT_TXT,
        required=True,
        widget=forms.TextInput(
            attrs={
                "id": "contact_subject",
                "name": "contact_subject",
                "type": "text",
                "placeholder": SUBJECT_TXT,
                "class": "form-control",
                'aria-label': SUBJECT_TXT,
                'aria-describedby': 'contact_subject'
            }
        )
    )

    email = forms.CharField(
        label=EMAIL_TXT,
        required=True,
        widget=forms.EmailInput(
            attrs={
                "id": "contact_email",
                "name": "contact_email",
                "type": "email",
                "placeholder": EMAIL_TXT,
                "class": "form-control",
                'aria-label': EMAIL_TXT,
                'aria-describedby': 'contact_email'
            }
        )
    )

    message = forms.CharField(
        label=MESSAGE_TXT,
        required=True,
        widget=forms.Textarea(
            attrs={
                "id": "contact_message",
                "name": "contact_message",
                "placeholder": MESSAGE_TXT,
                "class": "form-control",
                'aria-label': MESSAGE_TXT,
                'aria-describedby': 'contact_message',
                'rows': 2
            }
        )
    )

    unique_id = forms.UUIDField(
        widget=forms.HiddenInput(
            attrs={
                "id": "unique_id",
                "name": "unique_id",
                "type": "hidden",
                "value": UNIQUE_ID_INITIAL_VALUE
            }
        ),
        initial=UNIQUE_ID_INITIAL_VALUE,
    )

    captcha = ReCaptchaField(
        required=True,
        label=''
    )

    class Meta:
        model = ContactModel
        fields = '__all__'
