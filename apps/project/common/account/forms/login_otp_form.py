# apps/project/common/account/forms/login_otp_form.py
"""
El formulario de la entrada por código: a quién, y qué código.

Un solo formulario con los dos campos, no dos pantallas seguidas. La pantalla
enseña el identificador y el código a la vez, con un botón que manda el correo
y otro que entra; quien llega a ella ya sabe qué le van a pedir y no descubre a
mitad de camino que había un segundo paso.

El envío del código no pasa por aquí: lo atiende la vista antes de validar
nada, porque pedir el correo no puede exigir un código que todavía no existe.
Este formulario es el de entrar.
"""

from django import forms
from django.utils.translation import gettext_lazy as _


class LoginOTPForm(forms.Form):
    """
    Identificador y código, juntos.

    No comprueba que la cuenta exista, y no es un descuido: contestar «no
    existe» convertiría la pantalla en un comprobador de cuentas. Quien la
    rellena ve siempre lo mismo, y el correo sólo sale si hay a quién
    mandárselo.
    """

    identifier = forms.CharField(
        label=_('Username or Email'),
        max_length=254,
        widget=forms.TextInput(attrs={
            'autocomplete': 'username',
            'placeholder': ' ',
            'id': 'id_otp-identifier',
            'class': 'form-control',
        }),
    )

    code = forms.CharField(
        label=_('Verification code'),
        min_length=6,
        max_length=6,
        widget=forms.TextInput(attrs={
            'autocomplete': 'one-time-code',
            'inputmode': 'numeric',
            'pattern': '[0-9]*',
            'maxlength': '6',
            'placeholder': ' ',
            'id': 'id_otp-code',
            # Las clases van en el widget y no en un filtro de plantilla:
            # `add_class` reemplaza el atributo entero, así que ponerlas allí
            # borraría el centrado y el espaciado del código.
            'class': 'form-control text-center fs-4 fw-semibold',
            'style': 'letter-spacing:.4em;',
        }),
    )

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.user_cache = None

    def clean_identifier(self):
        return (self.cleaned_data['identifier'] or '').strip().lower()

    def clean_code(self):
        return (self.cleaned_data['code'] or '').strip()

    def clean(self):
        cleaned = super().clean()
        code = cleaned.get('code')
        identifier = cleaned.get('identifier') or ''

        if not code:
            return cleaned

        from apps.common.utils.login_attempts import is_locked_out, note_failure

        from ..otp_login import verify

        # Se pregunta por el bloqueo **antes** de mirar el código. Al revés se
        # apuntarían los fallos sin frenar nada, que es como estaba: el tope de
        # cinco intentos por código se esquiva pidiendo otro código.
        if is_locked_out(self.request, identifier):
            raise forms.ValidationError(_(
                'Too many failed attempts. Please wait before trying again.'))

        self.user_cache = verify(self.request, code)

        if self.user_cache is None:
            # El código erróneo cuenta igual que una contraseña errónea. Sin
            # esto, probar códigos de seis cifras salía gratis y el freno de la
            # contraseña sólo estorbaba a quien de verdad la había olvidado.
            note_failure(self.request, identifier, reason='login otp')

            # El mismo mensaje para un código equivocado, uno caducado y uno
            # que nunca se emitió. Distinguirlos le diría a quien prueba si la
            # cuenta existe, que es lo que la pantalla evita.
            raise forms.ValidationError(
                _('The code is not valid or has expired. Request a new one.'))

        return cleaned
