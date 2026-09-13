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

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _
from two_factor.forms import AuthenticationTokenForm, BackupTokenForm
from two_factor.views import LoginView as TwoFactorLoginView

from apps.common.utils.login_attempts import is_locked_out, note_failure
from apps.common.utils.wizards import forget_resolved_steps

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
        self._forget_resolved_steps()

    def _forget_resolved_steps(self):
        """
        Tira la lista de pasos que `formtools` guarda en caché.

        Nuestra condición del paso `otp` mira el modo, que vive en la sesión y
        cambia a mitad de petición; la caché de `formtools` no puede saberlo
        (ver `apps/common/utils/wizards.py`). Sin esto, entrar en modo código
        dejaba el paso `otp` como actual y luego lo buscaba en una lista
        resuelta **antes** del cambio: `KeyError: 'otp'`. Y al revés al salir.

        Se invalida aquí, en `_set_mode()`, y no en cada sitio que cambia de
        modo: es el único punto por el que pasa el cambio, y una invalidación
        que hay que acordarse de llamar es la que se olvida.
        """
        forget_resolved_steps(self)

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

        # Quitar el modo tambien cambia que pasos hay, asi que la caché de
        # `formtools` tiene que enterarse igual que al ponerlo.
        self._forget_resolved_steps()

        # `get_user()` puede devolver **False**, y eso no se puede pasar a
        # `login()`.
        #
        # El almacén del asistente guarda al usuario como dos datos sueltos
        # --`user_pk` y `user_backend`-- y su lector
        # (`two_factor.views.utils.LoginStorage`) devuelve `False`, no `None`,
        # cuando falta alguno o cuando el backend ya no puede cargar esa
        # cuenta. Si ese `False` llega a `login()`, Django intenta leerle un
        # atributo `backend`, no lo encuentra, y con tres backends
        # configurados acaba en:
        #
        #     ValueError: You have multiple authentication backends
        #     configured and therefore must provide the `backend` argument
        #
        # O sea: un 500 en la pantalla de acceso, con su traza, por un almacén
        # a medias. Eso puede pasar porque la sesión se perdiera entre dos
        # peticiones, porque quedara una sesión a medias de una versión
        # anterior, o porque la cuenta dejara de poder cargarse (se desactivó)
        # entre identificarse y terminar.
        #
        # En los tres casos la respuesta correcta es la misma y no es
        # reventar: no hay usuario, luego no hay acceso; se vacía lo que
        # quedara y se vuelve a empezar, diciéndolo. Se registra con todo el
        # contexto porque un reinicio silencioso es indistinguible de un botón
        # que no hace nada.
        if not self.get_user():
            return self._restart_without_user()

        return super().done(form_list, **kwargs)

    def _why_there_is_no_user(self) -> str:
        """
        Cuál de las dos cosas pasó, dicho en una línea.

        El lector del almacén devuelve `False` por dos motivos muy distintos y
        no dice cuál: o **no hay** `user_pk`/`user_backend` --la sesión se
        perdió-- o los hay pero **el backend no puede cargar esa cuenta** --no
        existe, o `user_can_authenticate()` la rechaza porque quedó
        `is_active=False`--. Uno se arregla mirando la sesión y el otro
        mirando la cuenta, así que confundirlos manda a buscar al sitio
        equivocado. Aquí se rehace la comprobación paso a paso para poder
        decirlo.

        Nunca lanza: esto se llama para explicar un fallo, y un diagnóstico
        que revienta deja sin diagnóstico y sin fallo original.
        """
        data = self.storage.data
        pk = data.get('user_pk')
        path = data.get('user_backend')

        if not pk or not path:
            return (
                f'el almacén no tiene al usuario (user_pk={"sí" if pk else "no"}, '
                f'user_backend={path or "no"}): se perdió la sesión entre la '
                f'petición que identificó y ésta'
            )

        try:
            from django.contrib.auth import load_backend

            backend = load_backend(path)
        except Exception as error:                      # noqa: BLE001
            return f'no se pudo cargar el backend {path}: {error!r}'

        if not hasattr(backend, 'get_user'):
            return (
                f'el backend anotado ({path}) no sabe cargar usuarios: no '
                f'tiene `get_user`. Ese no puede ser el backend de la sesión'
            )

        try:
            loaded = backend.get_user(pk)
        except Exception as error:                      # noqa: BLE001
            return f'{path}.get_user({pk!r}) levantó {error!r}'

        if loaded is not None:
            return (
                f'el backend sí carga a {pk}, así que el almacén cambió entre '
                f'la comprobación y ésta'
            )

        from django.contrib.auth import get_user_model

        exists = get_user_model()._default_manager.filter(pk=pk).first()

        if exists is None:
            # La cuenta ACABA de identificarse --si no, no habria pk-- y aun
            # asi no se encuentra por su clave. Eso no es «se borro entre dos
            # lineas»: es que la clave no viaja de vuelta.
            #
            # Hay dos causas conocidas, y **se distinguen por a que base
            # apunta la aplicacion**, que por eso se dice aqui:
            #
            # 1. La sesion viene de OTRA base. Un asistente a medias guardado
            #    en la sesion del navegador sobrevive a cambiar de base --por
            #    ejemplo al pasar de un tunel contra produccion a la copia
            #    local-- y entonces trae un pk que en esta no existe. Se
            #    reconoce porque la cuenta si esta en la otra, y porque el
            #    fallo es intermitente: en cuanto se vacia la sesion, entra.
            #
            # 2. El id no viaja de vuelta. Un UUID guardado **con guiones**
            #    ocupa 36 caracteres, se lee bien --y por eso `authenticate()`,
            #    que busca por username o por email_hash, lo encuentra-- pero
            #    `filter(pk=...)` manda el hex de 32 y no coincide con nada. Se
            #    reconoce contando en `apps_users_user` las filas cuyo `id` no
            #    mida 32 caracteres.
            #
            # El texto no lleva la consulta escrita: en este fichero no se
            # construye SQL, y dejar una cadena con forma de consulta obligaria
            # a aceptar el aviso de bandit para todo el modulo -- con lo que un
            # SQL de verdad entraria despues sin que nadie se enterara.
            return (
                f'no hay ninguna cuenta con pk={pk} en {self._which_database()}, '
                f'pero acaba de identificarse con esa clave. Las dos causas '
                f'conocidas: la sesion del navegador viene de otra base de '
                f'datos (un asistente a medias sobrevive al cambio), o el id '
                f'no viaja de vuelta porque en la tabla apps_users_user esta '
                f'guardado con guiones --36 caracteres-- y la consulta va con '
                f'el hex de 32'
            )

        return (
            f'la cuenta {pk} existe pero el backend la rechaza: '
            f'is_active={getattr(exists, "is_active", None)!r}'
        )

    def _which_database(self) -> str:
        """
        Contra qué base está mirando esto ahora mismo.

        Es el dato que separa las dos causas de que una cuenta recién
        identificada no se encuentre por su clave: si la sesión del navegador
        viene de otra base --un túnel contra producción y luego la copia
        local, por ejemplo-- el pk que trae no existe aquí, y el fallo es
        intermitente y desaparece al vaciar la sesión. Sin este dato, las dos
        causas se leen igual.

        **Sin contraseñas ni usuario.** Un log lo lee más gente que la que
        debería ver una credencial, y el nombre y el host bastan para saber a
        cuál de las dos bases se está hablando.
        """
        try:
            from django.db import connection

            ajustes = connection.settings_dict
            nombre = ajustes.get('NAME') or '(sin nombre)'
            host = ajustes.get('HOST') or 'local'
            puerto = ajustes.get('PORT') or ''

            return f'{nombre} en {host}:{puerto}' if puerto else f'{nombre} en {host}'
        except Exception:                               # noqa: BLE001
            return '(no se pudo saber qué base)'

    def _restart_without_user(self):
        """Vacía el asistente y devuelve a la primera pantalla, con aviso."""
        logger.warning(
            'Acceso: se llegó al final del asistente sin usuario en el '
            'almacén. paso=%s pasos=%s modo=%s. Motivo: %s',
            self.storage.current_step,
            list(self.get_form_list()),
            self._mode(),
            self._why_there_is_no_user(),
        )

        self.storage.reset()
        self.storage.current_step = self.AUTH_STEP
        self._set_mode(MODE_PASSWORD)

        aviso = _(
            'Your sign-in could not be completed because the session was '
            'lost. Please sign in again.'
        )

        # En desarrollo, el motivo va tambien a la pantalla. Quien esta
        # depurando esto no tiene por que ir a buscar el log --y si el log no
        # esta configurado como cree, no lo encuentra--; en produccion no sale,
        # porque diria a un desconocido si una cuenta existe o esta desactivada.
        if settings.DEBUG:
            aviso = f'{aviso} [DEBUG] {self._why_there_is_no_user()}'

        messages.error(self.request, aviso)

        # Se responde con una redirección y no repintando la pantalla: así el
        # navegador queda en un GET y volver a recargar no reenvía el
        # formulario a un asistente que ya no existe.
        return redirect(self.request.path)
