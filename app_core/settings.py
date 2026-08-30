import logging
import os
from datetime import timedelta
from pathlib import Path

from django.utils.translation import gettext_lazy as _
from dotenv import load_dotenv
from import_export.formats.base_formats import CSV, HTML, JSON, TSV, XLS, XLSX

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

logging.basicConfig(
    filename='stderr.log', format='%(asctime)s - %(levelname)s - %(message)s', encoding='utf-8'
)

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY')

if os.getenv('DJANGO_DEBUG') == 'True':
    DEBUG = True
    ALLOWED_HOSTS = ['*']
else:
    CSRF_COOKIE_SAMESITE = 'Strict'
    CSRF_COOKIE_SECURE = True
    DEBUG = False
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    X_FRAME_OPTIONS = 'DENY'
    if ',' in os.getenv('DJANGO_ALLOWED_HOSTS'):
        ALLOWED_HOSTS = os.getenv('DJANGO_ALLOWED_HOSTS').split(',')
    else:
        ALLOWED_HOSTS = [os.getenv('DJANGO_ALLOWED_HOSTS')]

ALLOW_ANY_EMAIL_IPCON = os.getenv(
    'ALLOW_ANY_EMAIL_IPCON', 'False').lower() == 'true'

DJANGO_APPS = [
    # No es 'django.contrib.admin': esta config instala GeaAdminSite, que
    # exige sesion con segundo factor y responde 404 a quien no cumple, en vez
    # de defenderse solo con lo secreta que sea ADMIN_URL. Ver app_core/admin.
    'app_core.apps.GeaAdminConfig',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.humanize',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sitemaps',
]

THIRD_PARTY_APPS = [
    'auditlog',
    'axes',
    'betterforms',
    'compressor',
    'corsheaders',
    'django_crontab',
    'django_filters',
    'django_otp',
    'django_otp.plugins.otp_static',
    'django_otp.plugins.otp_totp',
    'django_select2',
    'encrypted_model_fields',
    'formtools',
    'import_export',
    'parler',
    'rosetta',
    'two_factor',
    'impersonate',
    'django_countries',
]

COMMON_APPS = [
    'apps.common.core',
    'apps.common.utils',
]

PROJECT_ASSETS_MANAGEMENT_APPS = [
    'apps.project.specific.assets_management.assets',
    'apps.project.specific.assets_management.assets_location',
    'apps.project.specific.assets_management.buyers'
]

PROJECT_COMMON_APPS = [
    'apps.project.common.account',
    'apps.project.common.notifications',
    'apps.project.common.users',
]

PROJECT_DOCUMENTS_APPS = [
    'apps.project.specific.documents.certificates',
    'apps.project.specific.documents.video_masonry',
]

PROJECT_INTERNAL_APPS = [
    'apps.project.specific.internal.code_gen',
    'apps.project.specific.internal.ops',
]

ALL_CUSTOM_APPS = [
    *PROJECT_DOCUMENTS_APPS,
    *COMMON_APPS,
    *PROJECT_ASSETS_MANAGEMENT_APPS,
    *PROJECT_COMMON_APPS,
    *PROJECT_INTERNAL_APPS,
]

INSTALLED_APPS = [
    *ALL_CUSTOM_APPS,
    *DJANGO_APPS,
    *THIRD_PARTY_APPS,
]

# import_export
IMPORT_EXPORT_FORMATS = [CSV, HTML, JSON, TSV, XLS, XLSX]

LOGIN_URL = 'two_factor:login'

LOGIN_REDIRECT_URL = 'core:index'

# Django Parler and i18n
LOCALE_PATHS = [
    app_path / 'locale' for app_path in [BASE_DIR / app.replace('.', '/') for app in ALL_CUSTOM_APPS]
]

LOCALE_PATHS.append(str(BASE_DIR / 'app_core' / 'locale'))

LOCALE_PATHS.append(str(BASE_DIR / 'templates' / 'locale'))

LANGUAGE_CODE = 'en'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True

LANGUAGES = [
    ('es', 'Español'),
    ('en', 'English')
]

PARLER_LANGUAGES = {
    None: (
        {'code': 'es', },
        {'code': 'en', },
    ),
    'default': {
        'fallbacks': ['en'],
        'hide_untranslated': False,
    }
}

UTILS_PATH = 'apps.common.utils'
UTILS_DATA_PATH = f'{UTILS_PATH}.data'

ADMIN_URL = os.getenv('DJANGO_ADMIN_URL')

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    "corsheaders.middleware.CorsMiddleware",
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'auditlog.middleware.AuditlogMiddleware',
    'django_otp.middleware.OTPMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'apps.common.utils.middleware.RedirectWWWMiddleware',
    'apps.common.utils.middleware.RedirectAuthenticatedUserMiddleware',
    'apps.common.utils.middleware.BlockBadBotsMiddleware',
    'apps.common.utils.middleware.DetectSuspiciousRequestMiddleware',
    'axes.middleware.AxesMiddleware',
    'impersonate.middleware.ImpersonateMiddleware',
]

MIDDLEWARE_NOT_INCLUDE = [os.getenv('MIDDLEWARE_NOT_INCLUDE')]

ADMIN_DELETE_PERMISSION = True
ADMIN_ADD_PERMISSION = True

ROOT_URLCONF = 'app_core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.template.context_processors.i18n',
                'django.template.context_processors.media',
                'django.template.context_processors.static',
                'django.template.context_processors.tz',
                'django.contrib.messages.context_processors.messages',
                f'{UTILS_PATH}.context_processors.custom_processors'
            ],
        },
    },
]

WSGI_APPLICATION = 'app_core.wsgi.application'

ASGI_APPLICATION = 'app_core.asgi.application'

ENV_DB_ENGINE = os.getenv('DB_ENGINE')

DATABASES = {
    'default': {
        'ENGINE': ENV_DB_ENGINE,
        'NAME': os.getenv('DB_NAME'),
        'USER': os.getenv('DB_USER'),
        'PASSWORD': os.getenv('DB_PASSWORD'),
        'HOST': os.getenv('DB_HOST'),
        'PORT': int(os.getenv('DB_PORT')),
        'CONN_MAX_AGE': int(os.getenv('DB_CONN_MAX_AGE', 60)),
        'ATOMIC_REQUESTS': True,
        "OPTIONS": {
            "charset": "utf8mb4",
            "init_command": "SET NAMES utf8mb4 COLLATE utf8mb4_bin",
        }

    }
}

if ENV_DB_ENGINE == 'django.db.backends.mysql':
    DATABASES['default']['CHARSET'] = os.getenv('DB_CHARSET', 'utf8mb4')
    DATABASES['default']['OPTIONS'] = {
        "init_command": "SET SESSION time_zone = '+00:00', sql_mode='STRICT_TRANS_TABLES'"}

if not DEBUG and ENV_DB_ENGINE == 'django.db.backends.postgresql':
    DATABASES['default']['OPTIONS'] = {
        'sslmode': os.getenv('DB_SSLMODE', 'prefer')}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_USER_MODEL = 'users.UserModel'

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
        'OPTIONS': {
            'user_attributes': ('username', 'email', 'first_name', 'last_name'),
            'max_similarity': 0.7,
        }
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {
            'min_length': 8,
        }
    },
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'}
]

# El backend de axes va **primero**, y el orden no es cosmetico: cada backend
# se prueba en orden y el primero que devuelve un usuario gana. Con axes en
# segundo lugar, ``EmailOrUsernameModelBackend`` autenticaba antes y el bloqueo
# no llegaba a consultarse: durante el bloqueo, una contrasena equivocada daba
# 429 pero **la correcta entraba igual**. Es decir, el limite estorbaba al
# usuario legitimo de esa IP y no frenaba a quien acertaba la contrasena.
# ``AxesStandaloneBackend`` no autentica a nadie: o lanza ``PermissionDenied``
# porque hay bloqueo, o devuelve ``None`` y cede el paso al siguiente, asi que
# el login por correo o por usuario sigue funcionando igual.
AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',
    f'{UTILS_PATH}.backend.EmailOrUsernameModelBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# --- django-axes: freno a la fuerza bruta, sin dejar fuera a la oficina -----
# axes estaba instalado sin configurar, y sus valores por defecto son
# ``FAILURE_LIMIT = 3``, ``COOLOFF_TIME = None`` (bloqueo **permanente**),
# bloqueo **solo por IP** y ``RESET_ON_SUCCESS = False``. En una plataforma
# cuyo equipo comparte la salida a internet de una oficina, eso es un
# autobloqueo esperando a ocurrir: una persona tecleando mal su contrasena
# tres veces deja fuera a todos los demas, para siempre, hasta que alguien
# entre a la base de datos a mano. Y como los fallos no se olvidan tras un
# login correcto, la cuenta atras se agota sola con el paso de los meses.
#
# Se bloquea la pareja (IP, usuario), no la IP entera: quien se equivoca se
# frena a si mismo y el resto de la oficina sigue trabajando.
AXES_LOCKOUT_PARAMETERS = [['ip_address', 'username']]

AXES_FAILURE_LIMIT = int(os.getenv('AXES_FAILURE_LIMIT', 6))

AXES_COOLOFF_TIME = timedelta(
    minutes=int(os.getenv('AXES_COOLOFF_MINUTES', 30))
)

# Un login correcto borra los fallos previos de esa pareja. Sin esto, los
# despistes se acumulan durante meses hasta bloquear a alguien que no ha
# hecho nada raro.
AXES_RESET_ON_SUCCESS = True

# Sin esto lo de arriba no sirve: el login es un wizard y su campo se llama
# ``auth-username``, no ``username``, asi que axes guardaba todos los intentos
# con usuario vacio. El bloqueo por pareja degradaba a bloqueo por IP, y quien
# llegaba luego con la contrasena correcta se consultaba como una pareja sin
# fallos y entraba pese al bloqueo.
AXES_USERNAME_CALLABLE = f'{UTILS_PATH}.axes_hooks.username'

# Una sola respuesta a "de donde viene esta peticion" y una sola lista blanca,
# compartidas con la mitigacion anti-escaneo. Ver apps/common/utils/axes_hooks.
AXES_CLIENT_IP_CALLABLE = f'{UTILS_PATH}.axes_hooks.client_ip'
AXES_WHITELIST_CALLABLE = f'{UTILS_PATH}.axes_hooks.is_lockout_exempt'

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
]

SESSION_EXPIRE_AT_BROWSER_CLOSE = False

SESSION_COOKIE_AGE = 7200

ROSETTA_SHOW_AT_ADMIN_PANEL = True

# Base absoluta del sitio, usada cuando se generan URLs (QR de certificacion)
# fuera del ciclo de una peticion, por ejemplo desde una accion del admin.
# TODO(infra): configurar Redis y apuntar CACHES aqui.
#
# Sin CACHES definido Django usa LocMemCache, que es **por proceso**. Los
# limites de tasa del OTP publico (certificates/mixins.py) y el codigo de
# registro de compradores viven en cache: con N workers los limites son N
# veces mas laxos y se reinician en cada despliegue. Es el bypass mas facil
# de la unica superficie no autenticada que tiene la plataforma.
#
# El hosting actual (cPanel / Conexcol) no permite levantar Redis, asi que la
# salida es apuntar a un Redis en un VPS:
#
#     CACHES = {
#         'default': {
#             'BACKEND': 'django.core.cache.backends.redis.RedisCache',
#             'LOCATION': os.getenv('REDIS_URL'),   # rediss://... con TLS
#             'TIMEOUT': 300,
#         }
#     }
#
# Requisitos al montarlo: TLS obligatorio (el trafico sale del datacenter),
# contrasena, y la instancia cerrada por firewall a la IP del servidor web.
# Mientras tanto los limites siguen siendo por worker: no confiar en ellos
# como control de seguridad.

PUBLIC_BASE_URL = os.getenv(
    'PUBLIC_BASE_URL',
    'https://geausa.propensionesabogados.com'
).rstrip('/')

# Clave privada Ed25519 (32 bytes en base64) con la que se firma el registro
# de certificacion. Generala con:
#     uv run python manage.py generate_certification_key
# Sin ella el registro se sella con HMAC y solo la propia plataforma puede
# comprobarlo: un auditor externo no podria verificarlo por su cuenta.
CERTIFICATION_SIGNING_KEY = os.getenv('CERTIFICATION_SIGNING_KEY', '')

# Autoridad de sellado de tiempo (RFC 3161) para anclar el master hash de una
# caja AEGIS. Sin esta variable no se sella: no hay fallback silencioso.
#
# OJO: una TSA gratuita es tecnicamente identica pero NO tiene peso legal.
# Para fuerza probatoria hace falta un QTSP de la lista eIDAS o un proveedor
# acreditado ONAC (Certicamara). El sello se guarda tal cual lo devuelve la
# TSA, asi que cambiar de proveedor no invalida los ya emitidos.
CERTIFICATION_TSA_URL = os.getenv('CERTIFICATION_TSA_URL', '')
CERTIFICATION_TSA_USERNAME = os.getenv('CERTIFICATION_TSA_USERNAME', '')
CERTIFICATION_TSA_PASSWORD = os.getenv('CERTIFICATION_TSA_PASSWORD', '')

STATIC_URL = os.getenv('DJANGO_STATIC_URL')

STATIC_ROOT = str(os.getenv('DJANGO_STATIC_ROOT'))

MEDIA_URL = os.getenv('DJANGO_MEDIA_URL')

MEDIA_ROOT = str(os.getenv('DJANGO_MEDIA_ROOT'))

STATICFILES_DIRS = [str(BASE_DIR / 'public' / 'staticfiles')]

# Los estaticos se sirven con el hash del contenido en el nombre
# (styles.a1b2c3.css), asi que un JS o CSS actualizado deja de quedarse
# cacheado en el navegador hasta que expire. Obliga a ejecutar collectstatic
# antes de servir: si un fichero referenciado no existe, falla ahi y no en
# produccion.
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': (
            'django.contrib.staticfiles.storage.StaticFilesStorage'
            if DEBUG
            else 'django.contrib.staticfiles.storage.ManifestStaticFilesStorage'
        ),
    },
}

STATICFILES_FINDERS = (
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
    'compressor.finders.CompressorFinder',
)

EMAIL_USE_SSL = bool(os.getenv('DJANGO_EMAIL_USE_SSL'))
EMAIL_USE_TLS = not EMAIL_USE_SSL

DEFAULT_FROM_EMAIL = os.getenv('DJANGO_EMAIL_DEFAULT_FROM_EMAIL')
EMAIL_BACKEND = os.getenv('DJANGO_EMAIL_BACKEND')
EMAIL_HOST = os.getenv('DJANGO_EMAIL_HOST')
EMAIL_HOST_PASSWORD = os.getenv('DJANGO_EMAIL_HOST_PASSWORD')
EMAIL_HOST_USER = os.getenv('DJANGO_EMAIL_HOST_USER')
EMAIL_PORT = int(os.getenv('DJANGO_EMAIL_PORT'))


if ',' in os.getenv('GEA_DAILY_CODE_BUYER_RECIPIENTS'):
    GEA_DAILY_CODE_BUYER_RECIPIENTS = os.getenv(
        'GEA_DAILY_CODE_BUYER_RECIPIENTS').split(',')
else:
    GEA_DAILY_CODE_BUYER_RECIPIENTS = [
        os.getenv('GEA_DAILY_CODE_BUYER_RECIPIENTS')]


if ',' in os.getenv('GEA_DAILY_CODE_GENERAL_RECIPIENTS'):
    GEA_DAILY_CODE_GENERAL_RECIPIENTS = os.getenv(
        'GEA_DAILY_CODE_GENERAL_RECIPIENTS').split(',')
else:
    GEA_DAILY_CODE_GENERAL_RECIPIENTS = [
        os.getenv('GEA_DAILY_CODE_GENERAL_RECIPIENTS')]


CORS_ALLOWED_ORIGINS = list(os.getenv('CORS_ALLOWED_ORIGINS').split(','))

FIELD_ENCRYPTION_KEY = os.getenv('FIELD_ENCRYPTION_KEY')

DATA_UPLOAD_MAX_NUMBER_FIELDS = 15000

# Cron jobs
CRONJOBS = [
    # Madura las pruebas de OpenTimestamps: nacen sin bloque de Bitcoin y
    # entran en uno al cabo de unas horas. Que aun no este lista no es un
    # error; la pagina de anclaje se actualiza sola cuando confirma.
    ('15 * * * *', 'django.core.management.call_command',
     ['upgrade_ots_anchors']),
    ('0 19 * * *', 'apps.common.utils.cron.generate_and_send_gea_code'),
    ('*/3 * * * *', 'apps.common.utils.cron.warm_gea_app'),
]

# ChatGPT API Key
CHAT_GPT_API_KEY = os.getenv('CHAT_GPT_API_KEY')

# Block suspicious request settings
IP_BLOCKED_TIME_IN_MINUTES = int(os.getenv('IP_BLOCKED_TIME_IN_MINUTES'))

COMMON_ATTACK_TERMS = [
    term.strip() for term in os.getenv('COMMON_ATTACK_TERMS').split(',')
]
