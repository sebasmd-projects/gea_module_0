# apps/project/common/account/otp_login.py
"""
Entrar con un código enviado al correo, en vez de con la contraseña.

Sirve para dos cosas: para quien prefiere no teclear la contraseña, y --sobre
todo-- para quien la ha fallado tres veces y va camino del bloqueo de
``django-axes``. A la cuarta o quinta se queda fuera media hora; ofrecerle el
código en la tercera es lo que evita esa llamada al despacho.

Tres decisiones que conviene entender antes de tocar nada
--------------------------------------------------------

**El código no sustituye al segundo factor.** Va dentro del mismo asistente de
``django-two-factor-auth``, y lo único que hace es dejar el usuario
autenticado en el paso uno. Quien tenga un dispositivo TOTP configurado sigue
pasando por él después, porque el asistente añade ese paso él solo mirando el
dispositivo. Si esto viviera en una vista aparte que llamara a ``login()``,
tener acceso al correo bastaría para saltarse el 2FA de alguien: seria una
puerta trasera, no una comodidad.

**El código se guarda hasheado, nunca en claro.** HMAC-SHA256 sobre la
``SECRET_KEY`` y comparación en tiempo constante, igual que los OTP del portal
de certificados (invariante 4). Vive en la sesión, que en este proyecto va en
base de datos: sigue en pie aunque Redis se caiga.

**Preguntar por un usuario nunca dice si existe.** La respuesta es la misma
para una cuenta real y para una inventada --«si la cuenta existe, el código va
para allá»--, y el correo solo sale si hay a quién mandárselo. Lo contrario
convierte el formulario en un comprobador de cuentas, que es justo lo que el
resto del proyecto evita.
"""

import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.crypto import constant_time_compare

from apps.common.utils.functions import sha256_hex
from apps.common.utils.throttling import RateLimit

logger = logging.getLogger(__name__)

UserModel = get_user_model()

#: Dónde vive el estado del código dentro de la sesión.
SESSION_KEY = 'login_otp'

#: Cuánto dura. Quince minutos por defecto: lo que se pidió, y lo bastante
#: para buscar el correo en la bandeja de no deseado sin tener que repetir.
DEFAULT_TTL_MINUTES = 15

#: Cuántos códigos erróneos antes de invalidar el que hay. Se invalida el
#: código, no solo se bloquea la pantalla: la sesión la tira quien ataca de un
#: clic, el código no.
MAX_ATTEMPTS = 5

#: Cuántas contraseñas falladas antes de ofrecer el código. Tres, para llegar
#: antes que `AXES_FAILURE_LIMIT`, que por defecto son seis.
FAILURES_BEFORE_OFFER = 3

#: El cupo de envíos. Falla **cerrado**: el correo sale hacia el buzón de otra
#: persona, así que si el contador no se puede llevar no se manda --el mismo
#: razonamiento que en la recuperación de contraseña. Va por destinatario y no
#: por IP: quien pide el código elige su IP, quien lo recibe no.
send_throttle = RateLimit(
    'login_otp_send',
    limit=3,
    window=10 * 60,
)

#: Y el mismo envío por origen, que es lo que impide recorrer una lista de
#: usuarios mandando tres a cada uno.
send_ip_throttle = RateLimit(
    'login_otp_from',
    limit=15,
    window=10 * 60,
)


def ttl_minutes() -> int:
    return int(getattr(settings, 'LOGIN_OTP_TTL_MINUTES', DEFAULT_TTL_MINUTES))


def contact_email() -> str:
    return getattr(
        settings, 'LOGIN_OTP_CONTACT_EMAIL', 'info@propensionesabogados.com')


def generate_code() -> str:
    """Seis cifras, del generador criptográfico y no de ``random``."""
    return f'{secrets.randbelow(1_000_000):06d}'


def hash_code(code: str) -> str:
    return hmac.new(
        key=settings.SECRET_KEY.encode(),
        msg=code.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()


def backend_path() -> str:
    """
    Qué backend se apunta como responsable de esta autenticación.

    Django guarda esa ruta en la sesión para poder volver a cargar el usuario
    en cada petición; no vuelve a comprobar credenciales con ella. Se anota el
    backend de usuarios del propio proyecto --el mismo que deja puesto un
    acceso con contraseña-- para que las dos puertas dejen la sesión idéntica.

    No se puede anotar ``AxesStandaloneBackend``, que va el primero de la
    lista: ese no carga usuarios, solo vigila los intentos.
    """
    backends = list(getattr(settings, 'AUTHENTICATION_BACKENDS', []))

    for path in backends:
        if path.endswith('EmailOrUsernameModelBackend'):
            return path

    return 'django.contrib.auth.backends.ModelBackend'


def find_user(identifier: str):
    """
    El usuario detrás de un nombre o un correo, o ``None``.

    Se busca por `email_hash` y no por `email`, porque el correo está cifrado
    con Fernet --que no es determinista-- y `filter(email=...)` devuelve cero
    siempre. Es la misma razón por la que existe ese campo.
    """
    identifier = (identifier or '').strip().lower()

    if not identifier:
        return None

    if '@' in identifier:
        query = UserModel.objects.filter(email_hash=sha256_hex(identifier))
    else:
        query = UserModel.objects.filter(username=identifier)

    user = query.first()

    # Una cuenta desactivada no recibe código: dejarla entrar por esta puerta
    # seria saltarse la baja.
    if user and not user.is_active:
        return None

    return user


def issue(request, identifier: str) -> bool:
    """
    Emite un código para ese identificador y lo manda, si hay a quién.

    Devuelve si se llegó a mandar algo. **Quien llama no debe enseñar ese
    valor**: la pantalla dice lo mismo en los dos casos. Se devuelve para el
    log y para las pruebas.
    """
    from .emails import send_login_otp_email

    user = find_user(identifier)
    now = timezone.now()

    # El estado se guarda haya usuario o no, para que el paso siguiente exista
    # igual y la pantalla no delate por dónde se fue el flujo.
    request.session[SESSION_KEY] = {
        'identifier': (identifier or '').strip().lower(),
        'user_pk': str(user.pk) if user else '',
        'code_hash': '',
        'expires_at': (now + timedelta(minutes=ttl_minutes())).isoformat(),
        'attempts': 0,
    }

    if not user:
        logger.info('Login OTP requested for an unknown identifier')
        return False

    if not (user.email or '').strip():
        logger.warning('Login OTP requested for a user with no email: %s', user.pk)
        return False

    # Los dos cupos, no el primero que sobre: evaluar en corto dejaría uno sin
    # contar y el límite dependería del orden.
    to_ok = send_throttle.consume(request, scope=user.email)
    from_ok = send_ip_throttle.consume(request)

    if not (to_ok and from_ok):
        logger.warning('Login OTP send quota hit')
        return False

    code = generate_code()

    state = request.session[SESSION_KEY]
    state['code_hash'] = hash_code(code)
    request.session[SESSION_KEY] = state

    send_login_otp_email(user=user, code=code, minutes=ttl_minutes())

    return True


def state_of(request):
    return request.session.get(SESSION_KEY) or {}


def entered_identifier(request) -> str:
    """
    Lo que se tecleó, para devolverlo en pantalla.

    Se enseña tal cual y no enmascarado a propósito: es lo que acaba de
    escribir quien mira, no un dato que la pantalla revele. Lo que nunca sale
    de aquí es el correo de la cuenta, que sí diría si el identificador existe
    y a qué buzón está asociado.
    """
    return state_of(request).get('identifier', '')


def verify(request, code: str):
    """
    Comprueba el código y devuelve el usuario, o ``None``.

    Un código correcto se consume: el estado se borra entero, de modo que no
    vale dos veces ni sirve para volver atrás en el asistente.
    """
    state = state_of(request)

    if not state:
        return None

    expires_at = state.get('expires_at')
    try:
        expired = timezone.datetime.fromisoformat(expires_at) <= timezone.now()
    except (TypeError, ValueError):
        expired = True

    if expired:
        request.session.pop(SESSION_KEY, None)
        return None

    attempts = int(state.get('attempts', 0)) + 1
    state['attempts'] = attempts
    request.session[SESSION_KEY] = state

    if attempts > MAX_ATTEMPTS:
        # Se tira el código, no solo se corta la pantalla. Un tope que solo
        # cerrara la sesión lo esquiva quien borre la cookie.
        request.session.pop(SESSION_KEY, None)
        logger.warning('Login OTP invalidated after %s attempts', attempts)
        return None

    stored = state.get('code_hash') or ''

    # Sin código emitido --identificador desconocido, cuota agotada, usuario
    # sin correo-- no hay nada con que comparar. Se gasta el intento igual,
    # para que el camino cueste lo mismo mire quien mire.
    if not stored or not constant_time_compare(stored, hash_code((code or '').strip())):
        return None

    user_pk = state.get('user_pk')
    request.session.pop(SESSION_KEY, None)

    if not user_pk:
        return None

    user = UserModel.objects.filter(pk=user_pk, is_active=True).first()

    if user is None:
        return None

    # Django guarda en la sesión **qué backend** autenticó, para poder volver a
    # cargar el usuario en cada petición. `authenticate()` lo pone solo; un
    # usuario sacado del ORM a mano no lo trae, y sin él tanto `login()` como
    # el almacén del asistente de dos factores fallan con AttributeError.
    user.backend = backend_path()

    logger.info('Login OTP accepted for user %s', user.pk)

    return user


def clear(request) -> None:
    request.session.pop(SESSION_KEY, None)
