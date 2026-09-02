# apps/project/common/account/login_view.py
"""
El asistente de acceso, con una segunda puerta: el código por correo.

Por qué va **dentro** del asistente de ``django-two-factor-auth`` y no en una
vista aparte
------------------------------------------------------------------------
Porque el asistente decide él solo si hace falta el paso del segundo factor,
mirando si el usuario tiene dispositivo configurado. Lo único que hacen los
pasos nuevos es dejar el usuario autenticado en el primer paso, exactamente
como hace el formulario de contraseña; a partir de ahí el flujo es el de
siempre y el TOTP se sigue pidiendo.

Una vista aparte que llamara a ``login()`` habría sido mucho más corta y
habría convertido el acceso al correo en una forma de saltarse el segundo
factor de otra persona. Eso no es una comodidad, es una puerta trasera.

Los pasos
---------
El asistente tiene ahora cinco:

    auth      usuario y contraseña      ← siempre disponible
    otp_id    a quién mandar el código  ─┐ solo en modo código
    otp_code  el código de seis cifras  ─┘
    token     el segundo factor, si lo hay
    backup    el código de respaldo

Los dos del código entran y salen según el modo, que se guarda en la sesión y
no en el almacén del asistente --ese se vacía en mitad del camino y se
llevaría el modo con él, cambiando la lista de pasos a media pasada.

**El de contraseña no sale nunca.** Es lo que separa ofrecer el código de
capar los intentos: si al ofrecerlo se quitara ``auth`` de la lista, un envío
de contraseña posterior no llegaría a validarse, ``django-axes`` no contaría
ese fallo y su bloqueo --seis intentos-- no se alcanzaría jamás desde el
navegador. La oferta llegaría antes que el freno y de paso lo apagaría. Con
el paso siempre presente, quien quiera seguir probando la contraseña sigue
gastando intentos y el freno funciona igual que antes.
"""

import logging
import time

from two_factor.forms import AuthenticationTokenForm, BackupTokenForm
from two_factor.views import LoginView as TwoFactorLoginView

from . import otp_login
from .forms import LoginOTPCodeForm, LoginOTPIdentifierForm

logger = logging.getLogger(__name__)

#: Dónde se recuerda por qué puerta se entró. Fuera del almacén del asistente
#: a propósito: ese se vacía y se llevaría el modo con él.
MODE_KEY = 'login_mode'
FAILURES_KEY = 'login_password_failures'

#: Si ya se ofreció el código en este intento. La oferta es una sola: volver a
#: ofrecerlo en cada fallo posterior devolvería a la pantalla del código a
#: quien acaba de pedir expresamente seguir con la contraseña, y de hecho le
#: impediría llegar a gastar el cuarto intento.
OFFERED_KEY = 'login_otp_offered'

MODE_PASSWORD = 'password'
MODE_OTP = 'otp'


class GeaLoginView(TwoFactorLoginView):
    """El asistente de siempre, más la entrada por código."""

    OTP_ID_STEP = 'otp_id'
    OTP_CODE_STEP = 'otp_code'

    form_list = (
        (TwoFactorLoginView.AUTH_STEP, TwoFactorLoginView.form_list[0][1]),
        (OTP_ID_STEP, LoginOTPIdentifierForm),
        (OTP_CODE_STEP, LoginOTPCodeForm),
        (TwoFactorLoginView.TOKEN_STEP, AuthenticationTokenForm),
        (TwoFactorLoginView.BACKUP_STEP, BackupTokenForm),
    )

    def get_prefix(self, request, *args, **kwargs):
        """
        El prefijo del asistente se queda como estaba: ``login_view``.

        ``formtools`` lo saca del nombre de la clase, así que heredar de
        ``LoginView`` con otro nombre renombra de paso el campo oculto que la
        página envía --``login_view-current_step`` pasaría a ser
        ``gea_login_view-current_step``-- y la clave del almacén en la sesión.
        Lo primero es parte del contrato de la pantalla de acceso y está
        escrito en `tests_login.py`; lo segundo deja tirado a quien tuviera un
        acceso a medias en el momento del despliegue. Ninguna de las dos cosas
        tiene por qué cambiar porque la vista se llame de otra forma.
        """
        return 'login_view'

    # ------------------------------------------------------------------
    # Qué pasos entran
    # ------------------------------------------------------------------
    def _mode(self):
        return self.request.session.get(MODE_KEY, MODE_PASSWORD)

    def _set_mode(self, mode):
        self.request.session[MODE_KEY] = mode

    def has_otp_id_step(self):
        return self._mode() == MODE_OTP

    def has_otp_code_step(self):
        return self._mode() == MODE_OTP

    #: ``AUTH_STEP`` no aparece aquí a propósito: sin condición, el asistente
    #: lo incluye siempre. Ver el encabezado del módulo.
    condition_dict = {
        OTP_ID_STEP: has_otp_id_step,
        OTP_CODE_STEP: has_otp_code_step,
        TwoFactorLoginView.TOKEN_STEP: TwoFactorLoginView.has_token_step,
        TwoFactorLoginView.BACKUP_STEP: TwoFactorLoginView.has_backup_step,
    }

    # ------------------------------------------------------------------
    # Entrar y salir del modo código
    # ------------------------------------------------------------------
    def post(self, *args, **kwargs):
        request = self.request

        # El botón «entrar con código». Reinicia el asistente para no arrastrar
        # nada del intento anterior.
        if 'use_otp' in request.POST:
            self._set_mode(MODE_OTP)
            otp_login.clear(request)
            self.storage.reset()
            self.storage.current_step = self.OTP_ID_STEP
            return self.render(self.get_form())

        if 'use_password' in request.POST:
            self._set_mode(MODE_PASSWORD)
            otp_login.clear(request)
            self.storage.reset()
            self.storage.current_step = self.AUTH_STEP
            return self.render(self.get_form())

        return super().post(*args, **kwargs)

    def step_requires_authentication(self, step):
        """
        Qué pasos exigen que el usuario ya esté identificado.

        Los dos del código **no**: son los que identifican, igual que el de
        contraseña. La biblioteca da por hecho que solo el primer paso está
        antes de la identificación, y con el reloj de caducidad eso se traduce
        en que, al enviar el código, el asistente lo tomaba por una sesión
        caducada --``authentication_time`` todavía no existe, así que la cuenta
        sale negativa--, reiniciaba el almacén y devolvía a pedir el correo sin
        haber llegado a mirar el código. Ni error en pantalla, ni intento
        contado: parecía que el botón no hacía nada.
        """
        if step in (self.OTP_ID_STEP, self.OTP_CODE_STEP):
            return False

        return super().step_requires_authentication(step)

    # ------------------------------------------------------------------
    def get_form_kwargs(self, step=None):
        kwargs = super().get_form_kwargs(step)

        if step == self.OTP_CODE_STEP:
            kwargs['request'] = self.request

        return kwargs

    def process_step(self, form):
        """
        Lo que pasa al superar cada paso.

        Los dos pasos del código hacen entre los dos lo que el paso de
        contraseña hace de una vez: el primero manda el correo, el segundo
        deja el usuario autenticado.
        """
        step = self.steps.current

        if step == self.AUTH_STEP:
            # La contraseña acertó, así que el rodeo del código termina aquí.
            # Si el modo siguiera puesto, los dos pasos del código seguirían en
            # la lista y el asistente pediría a continuación un correo a quien
            # acaba de identificarse.
            self._set_mode(MODE_PASSWORD)
            otp_login.clear(self.request)

        if step == self.OTP_ID_STEP:
            otp_login.issue(self.request, form.cleaned_data['identifier'])
            # No se guarda nada del paso: el identificador ya está en el
            # estado del código, y repetirlo en el almacén del asistente sería
            # dejarlo escrito en dos sitios.
            return None

        if step == self.OTP_CODE_STEP:
            # Sin `storage.reset()`, al contrario que el paso de contraseña.
            #
            # Allí el reinicio existe para no dejar la contraseña escrita en la
            # sesión, y funciona porque `auth` es a la vez el primer paso y el
            # último. Aquí no: reiniciar devuelve `current_step` a `otp_id`, el
            # asistente deja de ver que está en el último paso y en vez de
            # terminar vuelve a pedir el código, en bucle.
            #
            # Y no hace falta: ninguno de los dos pasos guarda nada --los dos
            # devuelven `None`-- y el código ya lo consumió `verify()`.
            self.storage.authenticated_user = form.user_cache

            # El mismo sello que pone el paso de contraseña. Es el que mira
            # `expired` para los pasos que vienen después --el segundo factor
            # y el de respaldo--; sin él esos dos se tomarían por una sesión
            # caducada nada más llegar.
            self.storage.data['authentication_time'] = int(time.time())

            self.request.session.pop(FAILURES_KEY, None)
            return None

        return super().process_step(form)

    def get_done_form_list(self):
        """
        Qué formularios se revalidan al terminar.

        Ninguno de los tres primeros: no se guarda lo que se teclea en ellos
        --ni la contraseña, ni el identificador, ni el código-- así que
        revalidarlos sería validar formularios vacíos y el acceso fallaría
        siempre. La biblioteca hace lo mismo con el suyo, por lo mismo.
        """
        # `super()` hace `pop(AUTH_STEP)` sin valor por defecto, y en modo
        # código ese paso no está en la lista: reventaría con KeyError. Por eso
        # se parte de `get_form_list()` y se quitan los tres a la vez.
        form_list = self.get_form_list()

        for step in (self.AUTH_STEP, self.OTP_ID_STEP, self.OTP_CODE_STEP):
            form_list.pop(step, None)

        return form_list

    # ------------------------------------------------------------------
    # Las tres contraseñas falladas
    # ------------------------------------------------------------------
    def render(self, form=None, **kwargs):
        """
        Cuenta los fallos de contraseña y, al tercero, ofrece el código.

        Se cuenta aquí y no en `process_step` porque ese solo se llama con el
        formulario válido, y lo que hay que contar es justo lo contrario.

        A la tercera se cambia de modo, se emite el código y se salta al paso
        de teclearlo: se llega antes que `AXES_FAILURE_LIMIT` --seis por
        defecto-- que es media hora fuera.
        """
        failed_auth = (
            self.request.method == 'POST'
            and self.steps.current == self.AUTH_STEP
            and form is not None
            and form.is_bound
            and bool(form.errors)
        )

        if failed_auth:
            failures = int(self.request.session.get(FAILURES_KEY, 0)) + 1
            self.request.session[FAILURES_KEY] = failures

            already_offered = bool(self.request.session.get(OFFERED_KEY))
            identifier = (form.data.get('auth-username') or '').strip()

            if (failures >= otp_login.FAILURES_BEFORE_OFFER
                    and not already_offered and identifier):
                self.request.session[OFFERED_KEY] = True
                self._set_mode(MODE_OTP)
                self.storage.reset()

                # El envío pasa por su cupo, que falla cerrado. Si no hay
                # cupo, la pantalla sale igual: el mensaje no promete que
                # el correo salió, y decir aquí que no salió delataría que
                # la cuenta existe.
                otp_login.issue(self.request, identifier)

                self.storage.current_step = self.OTP_CODE_STEP
                return super().render(self.get_form(), **kwargs)

        return super().render(form, **kwargs)

    # ------------------------------------------------------------------
    def get_context_data(self, form, **kwargs):
        context = super().get_context_data(form, **kwargs)

        context['login_mode'] = self._mode()
        context['otp_identifier'] = otp_login.entered_identifier(self.request)
        context['otp_minutes'] = otp_login.ttl_minutes()
        context['otp_contact_email'] = otp_login.contact_email()
        context['password_failures'] = int(
            self.request.session.get(FAILURES_KEY, 0))
        context['otp_failures_before_offer'] = otp_login.FAILURES_BEFORE_OFFER
        context['otp_step_names'] = (self.OTP_ID_STEP, self.OTP_CODE_STEP)

        return context

    def done(self, form_list, **kwargs):
        # Que no quede nada del camino: ni el modo, ni el contador, ni el
        # código. Si no, el siguiente que entre por este navegador se
        # encontraría el asistente a medias.
        self.request.session.pop(MODE_KEY, None)
        self.request.session.pop(FAILURES_KEY, None)
        self.request.session.pop(OFFERED_KEY, None)
        otp_login.clear(self.request)

        return super().done(form_list, **kwargs)
