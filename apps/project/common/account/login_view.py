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

    auth    usuario y contraseña           ← siempre presente
    otp     usuario/correo **y** el código ← sólo en modo código
    token   el segundo factor, si lo hay
    backup  el código de respaldo

**El código es una sola pantalla, no dos.** Enseña el identificador y el
código a la vez, con un botón que manda el correo y otro que entra. Partirlo
en dos pasos --escribe el correo, pulsa, ahora escribe el código-- obligaba a
descubrir a mitad de camino que había un segundo tramo, y dejaba al asistente
con un paso cuyo único contenido era un campo ya escrito en el anterior.

**El de contraseña no sale nunca.** Es lo que separa ofrecer el código de
capar los intentos: si al ofrecerlo se quitara ``auth`` de la lista, un envío
de contraseña posterior no llegaría a validarse, ``django-axes`` no contaría
ese fallo y su bloqueo --seis intentos-- no se alcanzaría jamás desde el
navegador. La oferta llegaría antes que el freno y de paso lo apagaría.

**Los tres caminos cuentan en el mismo sitio.** Contraseña, código y segundo
factor apuntan sus fallos con `login_attempts.note_failure()` y preguntan por
el bloqueo con `is_locked_out()`. Antes sólo contaba la contraseña, así que el
camino más barato para quien atacaba era justo el que no dejaba rastro.
"""

import logging
import time

from django.utils.translation import gettext_lazy as _
from two_factor.forms import AuthenticationTokenForm, BackupTokenForm
from two_factor.views import LoginView as TwoFactorLoginView

from apps.common.utils.login_attempts import is_locked_out, note_failure

from . import otp_login
from .forms import LoginOTPForm

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

#: Con qué texto se identificó quien está entrando. Hace falta guardarlo
#: porque el segundo factor llega cuando ya no hay campo de usuario en
#: pantalla, y `django-axes` cuenta por lo **tecleado**, no por el usuario
#: resuelto: `UserModel.USERNAME_FIELD` es el correo, así que quien entra
#: como «ana» y falla el segundo factor alimentaría una cuenta atrás distinta
#: de la del primer paso. Dos contadores para el mismo intruso son ninguno:
#: bastaría con alternar de puerta para no agotar ninguna.
ATTEMPT_KEY = 'login_attempt_username'

MODE_PASSWORD = 'password'
MODE_OTP = 'otp'

#: El botón «enviar el código». Va por su nombre en el POST y no por un paso
#: del asistente porque no es un paso: no valida nada, manda un correo y
#: vuelve a pintar la misma pantalla.
SEND_ACTION = 'send_code'


class GeaLoginView(TwoFactorLoginView):
    """El asistente de siempre, más la entrada por código."""

    OTP_STEP = 'otp'

    form_list = (
        (TwoFactorLoginView.AUTH_STEP, TwoFactorLoginView.form_list[0][1]),
        (OTP_STEP, LoginOTPForm),
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

    def has_otp_step(self):
        return self._mode() == MODE_OTP

    #: ``AUTH_STEP`` no aparece aquí a propósito: sin condición, el asistente
    #: lo incluye siempre. Ver el encabezado del módulo.
    condition_dict = {
        OTP_STEP: has_otp_step,
        TwoFactorLoginView.TOKEN_STEP: TwoFactorLoginView.has_token_step,
        TwoFactorLoginView.BACKUP_STEP: TwoFactorLoginView.has_backup_step,
    }

    # ------------------------------------------------------------------
    # Entrar y salir del modo código
    # ------------------------------------------------------------------
    def _enter_otp_mode(self, identifier='', send=True):
        """
        Deja el asistente en la pantalla del código, con el correo mandado.

        `send` sale en False cuando sólo se quiere abrir la pantalla --el botón
        «entrar con un código»--, porque ahí todavía no se sabe a quién
        mandarlo.
        """
        self._set_mode(MODE_OTP)
        self.storage.reset()

        identifier = (identifier or '').strip()

        if send and identifier:
            # El envío pasa por su cupo, que falla cerrado. Si no hay cupo, la
            # pantalla sale igual: el mensaje no promete que el correo salió, y
            # decir aquí que no salió delataría que la cuenta existe.
            otp_login.issue(self.request, identifier)
        elif identifier:
            otp_login.remember_identifier(self.request, identifier)

        self.storage.current_step = self.OTP_STEP

    def post(self, *args, **kwargs):
        request = self.request

        # «Entrar con un código»: abre la pantalla, todavía sin mandar nada.
        # Quien lo pulsa puede no haber escrito su usuario aún.
        if 'use_otp' in request.POST:
            otp_login.clear(request)
            self._enter_otp_mode(
                request.POST.get('auth-username', ''), send=False)
            return self.render(self.get_form())

        # «Enviar el código»: manda el correo y vuelve a la misma pantalla.
        # No pasa por la validación del formulario porque el código todavía no
        # existe; exigirlo para poder pedirlo sería un círculo.
        if SEND_ACTION in request.POST:
            self._enter_otp_mode(request.POST.get('otp-identifier', ''))
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

        El del código **no**: es el que identifica, igual que el de
        contraseña. La biblioteca da por hecho que sólo el primer paso está
        antes de la identificación, y con el reloj de caducidad eso se traduce
        en que, al enviar el código, el asistente lo tomaba por una sesión
        caducada --``authentication_time`` todavía no existe, así que la cuenta
        sale negativa--, reiniciaba el almacén y devolvía a pedir el correo sin
        haber llegado a mirar el código. Ni error en pantalla, ni intento
        contado: parecía que el botón no hacía nada.
        """
        if step == self.OTP_STEP:
            return False

        return super().step_requires_authentication(step)

    # ------------------------------------------------------------------
    def get_form_kwargs(self, step=None):
        kwargs = super().get_form_kwargs(step)

        if step == self.OTP_STEP:
            kwargs['request'] = self.request

        return kwargs

    def get_form_initial(self, step):
        initial = super().get_form_initial(step)

        if step == self.OTP_STEP:
            # El identificador que ya se tecleó vuelve escrito. Volver a
            # pedirlo después de pulsar «enviar» haría dudar de si el correo
            # llegó a salir.
            initial = dict(initial or {})
            initial.setdefault(
                'identifier', otp_login.entered_identifier(self.request))

        return initial

    def process_step(self, form):
        """
        Lo que pasa al superar cada paso.

        El paso del código hace lo mismo que el de contraseña: dejar el usuario
        autenticado. Lo que venga después --el segundo factor-- es idéntico
        para los dos.
        """
        step = self.steps.current

        if step in (self.AUTH_STEP, self.OTP_STEP):
            self.request.session[ATTEMPT_KEY] = self._attempted_username(form)

        if step == self.AUTH_STEP:
            # La contraseña acertó, así que el rodeo del código termina aquí.
            # Si el modo siguiera puesto, su paso seguiría en la lista y el
            # asistente pediría a continuación un correo a quien acaba de
            # identificarse.
            self._set_mode(MODE_PASSWORD)
            otp_login.clear(self.request)

        if step == self.OTP_STEP:
            # Sin `storage.reset()`, al contrario que el paso de contraseña.
            #
            # Allí el reinicio existe para no dejar la contraseña escrita en la
            # sesión, y funciona porque `auth` es a la vez el primer paso y el
            # último. Aquí no: reiniciar devuelve `current_step` al principio,
            # el asistente deja de ver que está en el último paso y en vez de
            # terminar vuelve a pedir el código, en bucle.
            #
            # Y no hace falta: el paso no guarda nada --devuelve `None`-- y el
            # código ya lo consumió `verify()`.
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

        Ni el de contraseña ni el del código: no se guarda lo que se teclea en
        ellos, así que revalidarlos sería validar formularios vacíos y el
        acceso fallaría siempre. La biblioteca hace lo mismo con el suyo, por
        lo mismo.
        """
        # `super()` hace `pop(AUTH_STEP)` sin valor por defecto, y en modo
        # código ese paso podría no estar: se parte de `get_form_list()` y se
        # quitan los dos a la vez.
        form_list = self.get_form_list()

        for step in (self.AUTH_STEP, self.OTP_STEP):
            form_list.pop(step, None)

        return form_list

    # ------------------------------------------------------------------
    # Los fallos, que ahora cuentan los tres
    # ------------------------------------------------------------------
    def _attempted_username(self, form):
        """Quién intentaba entrar, mire el paso que mire."""
        step = self.steps.current

        if step == self.AUTH_STEP:
            return (form.data.get('auth-username') or '').strip()

        if step == self.OTP_STEP:
            return (form.data.get('otp-identifier') or '').strip()

        # En el segundo factor y en el de respaldo ya no hay campo de usuario
        # en pantalla: se usa lo que se tecleó al identificarse. No
        # `get_user().get_username()`, que devuelve el correo y abriría una
        # segunda cuenta atrás para el mismo intento.
        return self.request.session.get(ATTEMPT_KEY, '')

    def render(self, form=None, **kwargs):
        """
        Cuenta los fallos y, al tercero de contraseña, ofrece el código.

        Se cuenta aquí y no en `process_step` porque ese sólo se llama con el
        formulario válido, y lo que hay que contar es justo lo contrario.

        El segundo factor y el de respaldo se apuntan igual. No pasaban por
        `authenticate()`, así que sus fallos no llegaban a axes: probar
        códigos TOTP salía gratis mientras que probar contraseñas no, y el
        freno estorbaba sólo a quien no atacaba.
        """
        failed = (
            self.request.method == 'POST'
            and form is not None
            and form.is_bound
            and bool(form.errors)
        )
        step = self.steps.current

        if failed and step in (self.TOKEN_STEP, self.BACKUP_STEP):
            note_failure(
                self.request, self._attempted_username(form),
                reason=f'login {step}')

        if failed and step == self.AUTH_STEP:
            failures = int(self.request.session.get(FAILURES_KEY, 0)) + 1
            self.request.session[FAILURES_KEY] = failures

            already_offered = bool(self.request.session.get(OFFERED_KEY))
            identifier = self._attempted_username(form)

            if (failures >= otp_login.FAILURES_BEFORE_OFFER
                    and not already_offered and identifier):
                self.request.session[OFFERED_KEY] = True
                self._enter_otp_mode(identifier)

                return super().render(self.get_form(), **kwargs)

        return super().render(form, **kwargs)

    # ------------------------------------------------------------------
    def get_context_data(self, form, **kwargs):
        context = super().get_context_data(form, **kwargs)

        step = self.steps.current

        context['login_mode'] = self._mode()
        context['otp_step_name'] = self.OTP_STEP
        context['otp_send_action'] = SEND_ACTION
        context['otp_minutes'] = otp_login.ttl_minutes()
        context['otp_contact_email'] = otp_login.contact_email()
        context['otp_code_sent'] = otp_login.has_live_code(self.request)
        context['password_failures'] = int(
            self.request.session.get(FAILURES_KEY, 0))
        context['otp_failures_before_offer'] = otp_login.FAILURES_BEFORE_OFFER

        # El aviso de bloqueo se pinta antes de que el paso lo compruebe, para
        # que quien ya está fuera no siga tecleando códigos que nadie va a
        # mirar.
        context['locked_out'] = (
            step in (self.OTP_STEP, self.TOKEN_STEP, self.BACKUP_STEP)
            and is_locked_out(self.request, self._attempted_username(form))
        )

        context['step_title'], context['step_lead'] = self._step_copy(step)

        return context

    def _step_copy(self, step):
        """Título y frase de cada pantalla, en un solo sitio."""
        if step == self.OTP_STEP:
            return (
                _('Sign in with a code'),
                _('We send a six-digit code to the email on your account.'),
            )

        if step == self.TOKEN_STEP:
            return (
                _('Two-step verification'),
                _('Enter the code from your authentication app.'),
            )

        if step == self.BACKUP_STEP:
            return (
                _('Backup token'),
                _('Enter one of the backup tokens you saved when you set up '
                  'two-step verification.'),
            )

        return (_('Sign in'), _('Enter your credentials to access GEA.'))

    def done(self, form_list, **kwargs):
        # Que no quede nada del camino: ni el modo, ni el contador, ni el
        # código. Si no, el siguiente que entre por este navegador se
        # encontraría el asistente a medias.
        self.request.session.pop(MODE_KEY, None)
        self.request.session.pop(FAILURES_KEY, None)
        self.request.session.pop(OFFERED_KEY, None)
        self.request.session.pop(ATTEMPT_KEY, None)
        otp_login.clear(self.request)

        return super().done(form_list, **kwargs)
