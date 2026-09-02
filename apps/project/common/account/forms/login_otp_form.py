# apps/project/common/account/forms/login_otp_form.py
"""
Los dos formularios de la entrada por código: a quién, y qué código.
"""

from django import forms
from django.utils.translation import gettext_lazy as _


class LoginOTPIdentifierForm(forms.Form):
    """
    A quién mandar el código.

    No valida que la cuenta exista, y no es un descuido: contestar «no existe»
    convertiría la pantalla en un comprobador de cuentas. Quien la rellena ve
    siempre lo mismo, y el correo solo sale si hay a quién mandárselo.
    """

    identifier = forms.CharField(
        label=_('Username or Email'),
        max_length=254,
        widget=forms.TextInput(attrs={
            'autocomplete': 'username',
            'autofocus': 'autofocus',
        }),
    )

    def clean_identifier(self):
        return (self.cleaned_data['identifier'] or '').strip().lower()


class LoginOTPCodeForm(forms.Form):
    """
    El código de seis cifras.

    Lleva el usuario dentro (`user_cache`) para que la vista lo recoja igual
    que recoge el del formulario de contraseña: así el asistente de dos
    factores sigue funcionando sin enterarse de por dónde entró.
    """

    code = forms.CharField(
        label=_('Verification code'),
        min_length=6,
        max_length=6,
        widget=forms.TextInput(attrs={
            'autocomplete': 'one-time-code',
            'inputmode': 'numeric',
            'pattern': '[0-9]*',
            'autofocus': 'autofocus',
        }),
    )

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.user_cache = None

    def clean_code(self):
        return (self.cleaned_data['code'] or '').strip()

    def clean(self):
        cleaned = super().clean()
        code = cleaned.get('code')

        if not code:
            return cleaned

        from ..otp_login import verify

        self.user_cache = verify(self.request, code)

        if self.user_cache is None:
            # El mismo mensaje para un código equivocado, uno caducado y uno
            # que nunca se emitió. Distinguirlos le diría a quien prueba si la
            # cuenta existe, que es lo que el paso anterior evita.
            raise forms.ValidationError(
                _('The code is not valid or has expired. Request a new one.'))

        return cleaned
