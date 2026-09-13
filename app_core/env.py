"""
Comprobacion del entorno: que falta en el `.env`, dicho por su nombre.

El problema
-----------
Muchos `os.getenv()` de `settings.py` se pasan directos a `int()` o a
`.split(',')` sin valor por defecto. Cuando falta una variable, el proyecto no
arranca --eso esta bien-- pero lo que se lee es esto:

    TypeError: int() argument must be a string ... not 'NoneType'
    AttributeError: 'NoneType' object has no attribute 'split'
    TypeError: argument of type 'NoneType' is not iterable

Ninguno nombra la variable. Hay que abrir `settings.py` por la linea de la
traza para averiguar de cual se trata, y repetir la operacion **una vez por
variable que falte**, porque el arranque muere en la primera.

Lo que hace esto
----------------
Una sola pasada, antes de que `settings.py` lea nada: se comprueban todas, y
si falta alguna se levanta un `ImproperlyConfigured` que las nombra **todas
juntas**, cada una con una linea de para que sirve. Un arranque, una lista, y
la plantilla de `docs/env.example` al pie.

Tres decisiones que no son de gusto
-----------------------------------
1. **Vacio cuenta como ausente**, salvo donde vacio significa algo. `DB_PORT=`
   rompe igual que no ponerlo (`int('')` tambien falla), y una clave de cifrado
   en blanco no es una clave. Las excepciones estan en `ALLOWED_EMPTY`, con su
   motivo: `CORS_ALLOWED_ORIGINS` vacio es "ningun origen", que es una
   respuesta valida, y una contrasena vacia es una contrasena posible.
2. **Hay variables que solo son obligatorias en produccion.**
   `DJANGO_ALLOWED_HOSTS` solo se lee en la rama de `DEBUG=False`; exigirla
   siempre convertiria en error un `.env` de portatil que hoy funciona, que es
   justo lo contrario de lo que se busca.
3. **Lo que se lee sin valor por defecto y aun asi puede faltar esta declarado
   aparte**, en `OPTIONAL_WITHOUT_DEFAULT`, con la razon escrita. No es
   decoracion: `test_env.py` recorre `settings.py`, y una variable nueva leida
   sin defecto que no este en ninguna de las dos listas falla la prueba. Asi la
   lista no se queda vieja sin que nadie lo note.
"""

import os

from django.core.exceptions import ImproperlyConfigured

# Donde esta la plantilla, para poder decirlo en el error.
ENV_EXAMPLE = 'docs/env.example'

# Obligatorias siempre. El texto es lo que se imprime al lado del nombre, asi
# que se escribe para quien acaba de ver el error y no conoce el proyecto.
REQUIRED = {
    'DJANGO_SECRET_KEY': (
        'Clave de firma de Django. Generala con '
        '`python -c "from django.core.management.utils import '
        'get_random_secret_key as k; print(k())"`.'
    ),
    'DJANGO_ADMIN_URL': (
        'Ruta donde cuelga el panel, sin barras (por ejemplo `panel-dev`).'
    ),
    'DJANGO_STATIC_URL': 'Prefijo de los estaticos, por ejemplo `/public/static/`.',
    'DJANGO_STATIC_ROOT': 'Carpeta donde `collectstatic` los deja.',
    'DJANGO_MEDIA_URL': 'Prefijo de los archivos subidos, por ejemplo `/public/media/`.',
    'DJANGO_MEDIA_ROOT': 'Carpeta donde se guardan los archivos subidos.',

    'DB_ENGINE': (
        'Backend de base de datos, con su ruta completa: '
        '`django.db.backends.mysql` o `django.db.backends.postgresql`.'
    ),
    'DB_NAME': 'Nombre de la base de datos.',
    'DB_USER': 'Usuario de la base de datos.',
    'DB_PASSWORD': 'Contrasena de la base de datos (puede ir vacia).',
    'DB_HOST': 'Host de la base de datos.',
    'DB_PORT': 'Puerto de la base de datos. Se convierte a entero.',

    'DJANGO_EMAIL_BACKEND': (
        'Backend de correo. En local, '
        '`django.core.mail.backends.console.EmailBackend` no manda nada.'
    ),
    'DJANGO_EMAIL_HOST': 'Servidor SMTP por el que sale el correo.',
    'DJANGO_EMAIL_PORT': 'Puerto SMTP. Se convierte a entero.',
    'DJANGO_EMAIL_HOST_USER': 'Usuario con el que se autentica el SMTP.',
    'DJANGO_EMAIL_HOST_PASSWORD': 'Contrasena SMTP (puede ir vacia).',
    'DJANGO_EMAIL_DEFAULT_FROM_EMAIL': 'Remitente por defecto.',

    'FIELD_ENCRYPTION_KEY': (
        'Clave Fernet con la que se cifra la PII en la base de datos. '
        'Generala con `python -c "from cryptography.fernet import Fernet; '
        'print(Fernet.generate_key().decode())"`. PERDERLA INUTILIZA LOS DATOS '
        'YA CIFRADOS.'
    ),
    'CORS_ALLOWED_ORIGINS': (
        'Origenes permitidos, separados por comas. Vacio es valido y '
        'significa ninguno.'
    ),
    'COMMON_ATTACK_TERMS': (
        'Terminos de la trampa anti-escaneo, separados por comas. Vacio es '
        'valido y desactiva la trampa. Tras tocarla: '
        '`manage.py check_attack_terms`.'
    ),
    'IP_BLOCKED_TIME_IN_MINUTES': (
        'Minutos del primer bloqueo por IP; se duplica en cada intento. Se '
        'convierte a entero.'
    ),

    'GEA_DAILY_CODE_BUYER_RECIPIENTS': (
        'A quien se manda el codigo diario de comprador, separados por comas.'
    ),
    'GEA_DAILY_CODE_GENERAL_RECIPIENTS': (
        'A quien se manda el codigo diario general, separados por comas.'
    ),
}

# Obligatorias solo con DEBUG=False: settings.py solo las lee en esa rama.
REQUIRED_IN_PRODUCTION = {
    'DJANGO_ALLOWED_HOSTS': (
        'Dominios que sirve la aplicacion, separados por comas. Con DEBUG=True '
        'no se lee, porque ahi ALLOWED_HOSTS es `*`.'
    ),
}

# Donde una cadena vacia es una respuesta y no un olvido.
ALLOWED_EMPTY = frozenset({
    'CORS_ALLOWED_ORIGINS',          # vacio = ningun origen permitido
    'COMMON_ATTACK_TERMS',           # vacio = trampa desactivada
    'DB_PASSWORD',                   # una base local puede no tener
    'DJANGO_EMAIL_HOST_PASSWORD',    # el backend de consola no la usa
})

# Se leen sin valor por defecto y aun asi pueden faltar. Cada una con el motivo
# por el que su ausencia no rompe nada, que es lo que hay que comprobar antes
# de anadir una entrada aqui en vez de a REQUIRED.
OPTIONAL_WITHOUT_DEFAULT = {
    'DJANGO_DEBUG': (
        'Su ausencia significa DEBUG=False, que es el lado seguro: un olvido '
        'aqui deja el servidor en modo produccion, no al reves.'
    ),
    'DJANGO_LOG_FILE': (
        'Tiene alternativa en la propia linea (`or BASE_DIR / stderr.log`).'
    ),
    'DJANGO_EMAIL_USE_SSL': (
        'Se pasa por `bool()`, asi que ausente es False y el correo sale sin '
        'SSL en vez de no arrancar.'
    ),
    'CHAT_GPT_API_KEY': (
        'La traduccion automatica es opcional: sin clave, `translate()` '
        'devuelve el texto original en vez de fallar.'
    ),
    'PQRS_NOTIFICATION_RECIPIENTS': (
        'Tiene alternativa en la propia linea (`or ""`). Ojo: sin ella no se '
        'avisa a nadie de una PQRS nueva, y el plazo legal corre igual.'
    ),
    'MIDDLEWARE_NOT_INCLUDE': (
        'Se declara y no lo consume nadie. `[None]` no rompe nada.'
    ),
}


def _is_set(name: str, value) -> bool:
    """¿Esta puesta? Vacia cuenta como ausente salvo en `ALLOWED_EMPTY`."""
    if value is None:
        return False

    if not value.strip():
        return name in ALLOWED_EMPTY

    return True


def expected_variables(debug: bool) -> dict:
    """Las que tienen que estar, segun el modo en que se arranque."""
    expected = dict(REQUIRED)

    if not debug:
        expected.update(REQUIRED_IN_PRODUCTION)

    return expected


def missing_variables(environ=None, debug=None) -> list:
    """Las que faltan, en el orden en que estan declaradas arriba."""
    environ = os.environ if environ is None else environ

    if debug is None:
        debug = environ.get('DJANGO_DEBUG') == 'True'

    return [
        (name, reason)
        for name, reason in expected_variables(debug).items()
        if not _is_set(name, environ.get(name))
    ]


def format_missing(missing: list, debug: bool = False) -> str:
    """El texto del error: los nombres primero, y la plantilla al final."""
    cuantas = (
        'Falta 1 variable de entorno'
        if len(missing) == 1
        else f'Faltan {len(missing)} variables de entorno'
    )

    lineas = [
        f'{cuantas} y el proyecto no puede arrancar sin ellas.',
        '',
        f'Se leen del fichero `.env` en la raiz del repositorio '
        f'(modo {"DEBUG" if debug else "produccion"}):',
        '',
    ]

    for name, reason in missing:
        lineas.append(f'  {name}')
        lineas.append(f'      {reason}')

    lineas += [
        '',
        f'La plantilla con todas, comentadas una a una, esta en {ENV_EXAMPLE}:',
        f'    cp {ENV_EXAMPLE} .env',
    ]

    return '\n'.join(lineas)


def check_environment(environ=None, debug=None) -> None:
    """
    Levanta `ImproperlyConfigured` nombrando todo lo que falte.

    Se llama desde `settings.py` justo despues de `load_dotenv()`, antes de que
    nadie lea una variable: asi el error es la lista completa y no la primera
    linea que se tropieza.
    """
    environ = os.environ if environ is None else environ

    if debug is None:
        debug = environ.get('DJANGO_DEBUG') == 'True'

    missing = missing_variables(environ, debug)

    if missing:
        raise ImproperlyConfigured(format_missing(missing, debug))
