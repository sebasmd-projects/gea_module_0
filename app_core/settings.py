import os
from datetime import date
from datetime import timedelta
from pathlib import Path

from django.utils.translation import gettext_lazy as _
from dotenv import load_dotenv
from import_export.formats.base_formats import CSV, HTML, JSON, TSV, XLS, XLSX

from app_core.db import engine_for
from app_core.env import check_environment

load_dotenv()

check_environment()

BASE_DIR = Path(__file__).resolve().parent.parent

LOG_FILE = Path(os.getenv('DJANGO_LOG_FILE') or (BASE_DIR / 'stderr.log'))

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'gea': {
            'format': (
                '%(asctime)s - %(levelname)s - %(name)s - %(message)s'
            ),
        },
    },
    'handlers': {
        'file': {
            'class': 'logging.handlers.WatchedFileHandler',
            'filename': str(LOG_FILE),
            'encoding': 'utf-8',
            'formatter': 'gea',
        },
    },
    'root': {
        'handlers': ['file'],
        'level': 'WARNING',
    },
    'loggers': {
        'django.request': {
            'handlers': ['file'],
            'level': 'WARNING',
            'propagate': False,
        },
        # El acceso del servidor de desarrollo no aporta nada al fichero.
        'django.server': {
            'handlers': [],
            'level': 'CRITICAL',
            'propagate': False,
        },
        'apps': {
            'handlers': ['file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY')

ALLOW_ANY_EMAIL_IPCON = os.getenv(
    'ALLOW_ANY_EMAIL_IPCON', 'False').lower() == 'true'

DJANGO_APPS = [
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
    'django_ckeditor_5',
    'axes',
    'compressor',
    'corsheaders',
    'django_crontab',
    'django_otp',
    'django_otp.plugins.otp_static',
    'django_otp.plugins.otp_totp',
    'django_select2',
    'encrypted_model_fields',
    'formtools',
    'import_export',
    'rosetta',
    'two_factor',
    'impersonate',
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
    'apps.project.common.pqrs',
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


if os.getenv('DJANGO_DEBUG') == 'True':
    DEBUG = True
    ALLOWED_HOSTS = ['*']
    try:
        INSTALLED_APPS.append("debug_toolbar")
        INTERNAL_IPS = ["127.0.0.1", "localhost"]
    except ImportError:
        pass
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


# import_export
IMPORT_EXPORT_FORMATS = [CSV, HTML, JSON, TSV, XLS, XLSX]

LOGIN_URL = 'two_factor:login'

LOGIN_REDIRECT_URL = 'core:index'

# --- Los códigos de seis cifras que se mandan por correo --------------------
LOGIN_OTP_TTL_MINUTES = int(os.getenv('LOGIN_OTP_TTL_MINUTES', 15))
OTP_TTL_MINUTES = int(os.getenv('OTP_TTL_MINUTES', 15))

OTP_CONTACT_EMAIL = os.getenv(
    'OTP_CONTACT_EMAIL', 'info@propensionesabogados.com')

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

if os.getenv('DJANGO_DEBUG') == 'True':
    MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")

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

# Con MySQL/MariaDB no se usa el backend de Django tal cual, sino el de
# `app_core/db/mysql`, que es el mismo con una sola diferencia: los UUID se
# siguen guardando como se guardaron.
#
# Django 5.0 empezo a usar el tipo nativo `uuid` de MariaDB 10.7+, y con el
# cambian los valores que van en CADA consulta: con guiones en vez del hex.
# Una base creada con 4.2 tiene `char(32)` con el hex, asi que al subir de
# version las busquedas **por clave primaria dejan de encontrar nada** --y
# nada falla: la fila se lee, `filter(username=...)` la encuentra, y solo
# `filter(pk=...)` se queda vacio--. En el acceso eso se vio como una
# contrasena aceptada y un asistente que no podia recargar al usuario.
DECLARED_DB_ENGINE = ENV_DB_ENGINE

ENV_DB_ENGINE = engine_for(DECLARED_DB_ENGINE)

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
        "OPTIONS": {},
    }
}

if DECLARED_DB_ENGINE == 'django.db.backends.mysql':
    DATABASES['default']['CHARSET'] = os.getenv('DB_CHARSET', 'utf8mb4')
    DATABASES['default']['OPTIONS'] = {
        "init_command": "SET SESSION time_zone = '+00:00', sql_mode='STRICT_TRANS_TABLES'"}

if not DEBUG and DECLARED_DB_ENGINE == 'django.db.backends.postgresql':
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

AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',
    f'{UTILS_PATH}.backend.EmailOrUsernameModelBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# --- django-axes: freno a la fuerza bruta, sin dejar fuera a la oficina -----
AXES_LOCKOUT_PARAMETERS = [['ip_address', 'username']]

AXES_FAILURE_LIMIT = int(os.getenv('AXES_FAILURE_LIMIT', 6))

AXES_COOLOFF_TIME = timedelta(
    minutes=int(os.getenv('AXES_COOLOFF_MINUTES', 30))
)

AXES_RESET_ON_SUCCESS = True

AXES_USERNAME_CALLABLE = f'{UTILS_PATH}.axes_hooks.username'

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

SESSION_COOKIE_HTTPONLY = True

SESSION_COOKIE_SAMESITE = 'Lax'

DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# Cuantos ficheros admite un solo envio. Sin tope, una peticion con miles de
# ficheros abre miles de descriptores antes de que nadie valide nada.
DATA_UPLOAD_MAX_NUMBER_FILES = 20

ROSETTA_SHOW_AT_ADMIN_PANEL = True

REDIS_URL = os.getenv('REDIS_URL', '').strip()

CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', '').strip()

if REDIS_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': REDIS_URL,
            'TIMEOUT': 300,
            'KEY_PREFIX': os.getenv('REDIS_KEY_PREFIX', 'gea'),
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',

                'IGNORE_EXCEPTIONS': True,

                'SOCKET_CONNECT_TIMEOUT': int(
                    os.getenv('REDIS_CONNECT_TIMEOUT', 3)
                ),
                'SOCKET_TIMEOUT': int(os.getenv('REDIS_TIMEOUT', 3)),
            },
        }
    }

    # Que el fallo se vea en el log en vez de desaparecer sin ruido.
    DJANGO_REDIS_LOG_IGNORED_EXCEPTIONS = True

PUBLIC_BASE_URL = os.getenv(
    'PUBLIC_BASE_URL',
    'https://geausa.propensionesabogados.com'
).rstrip('/')

# Clave privada Ed25519 (32 bytes en base64) con la que se firma el registro
# de certificacion. Generala con:
#     uv run python manage.py generate_certification_key
# Sin ella el registro se sella con HMAC y solo la propia plataforma puede
CERTIFICATION_SIGNING_KEY = os.getenv('CERTIFICATION_SIGNING_KEY', '')

CERTIFICATION_TSA_URL = os.getenv('CERTIFICATION_TSA_URL', '')
CERTIFICATION_TSA_USERNAME = os.getenv('CERTIFICATION_TSA_USERNAME', '')
CERTIFICATION_TSA_PASSWORD = os.getenv('CERTIFICATION_TSA_PASSWORD', '')

STATIC_URL = os.getenv('DJANGO_STATIC_URL')

STATIC_ROOT = str(os.getenv('DJANGO_STATIC_ROOT'))

MEDIA_URL = os.getenv('DJANGO_MEDIA_URL')

MEDIA_ROOT = str(os.getenv('DJANGO_MEDIA_ROOT'))

STATICFILES_DIRS = [str(BASE_DIR / 'public' / 'staticfiles')]

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
#
# `django-crontab` quiere la ruta del invocable **como cadena**, asi que una
# entrada que lanza un comando de `manage.py` repite siempre la misma. Escrita
# a mano en cada una, una errata no se ve al leer --son rutas largas y
# parecidas-- y la entrada simplemente no se ejecuta: `crontab_add` la instala
# igual, y el fallo aparece a la hora de la verdad, en el servidor y sin nadie
# delante.
#
# En minusculas a proposito: Django convierte en ajuste **todo nombre de
# modulo en mayusculas**, y esto no es configuracion de nadie. Un
# `CALL_COMMAND` en `settings` seria un ajuste mas que parece que se puede
# cambiar y no cambia nada — justo la trampa que §7 de CLAUDE.md ya documenta
# con `MIDDLEWARE_NOT_INCLUDE` y compania.
_call_command = 'django.core.management.call_command'

CRONJOBS = [
    ('*/15 * * * *', _call_command, ['upgrade_ots_anchors']),
    ('0 19 * * *', 'apps.common.utils.cron.generate_and_send_gea_code'),
    ('*/3 * * * *', 'apps.common.utils.cron.warm_gea_app'),
    ('0 * * * *', _call_command, ['rotate_logs']),

    # El aviso de un cambio en un documento legal. Cada media hora y no cada
    # minuto porque aprobar un texto pasa tres veces al año; sin nada pendiente
    # es una consulta y se va. Va por cron y no dentro de la peticion de
    # aprobar porque mandar cientos de correos con ATOMIC_REQUESTS puesto
    # tendria la transaccion abierta todo ese rato.
    ('*/30 * * * *', _call_command, ['notify_legal_changes']),
]

# --- Documentos legales ------------------------------------------------
#
# La version, la fecha de vigencia y el estado ya NO se configuran aqui: viven
# en `LegalDocumentVersionModel`, que es el unico sitio donde no pueden
# contradecir al texto publicado. Lo que queda aqui es como se redacta.
#
# La configuracion del editor de los documentos legales.
#
# La barra es corta a proposito. Lo que se redacta aqui es un texto juridico
# que ademas se convierte en PDF, y cada boton de mas es una etiqueta que el
# convertidor de `legal_pdf.py` tiene que saber pintar: un color de fondo o una
# fuente rara no llegan al papel, asi que ofrecerlos es prometer algo que no se
# cumple. Lo que hay aqui es exactamente lo que el PDF sabe reproducir.
CKEDITOR_5_CONFIGS = {
    'legal': {
        'toolbar': [
            'heading', '|',
            'bold', 'italic', 'link', '|',
            'bulletedList', 'numberedList', '|',
            'insertTable', 'blockQuote', '|',
            'undo', 'redo', 'sourceEditing',
        ],
        'heading': {
            'options': [
                {'model': 'paragraph', 'title': 'Parrafo',
                 'class': 'ck-heading_paragraph'},
                {'model': 'heading2', 'view': 'h2', 'title': 'Apartado',
                 'class': 'ck-heading_heading2'},
                {'model': 'heading3', 'view': 'h3', 'title': 'Subapartado',
                 'class': 'ck-heading_heading3'},
            ]
        },
        'table': {
            'contentToolbar': ['tableColumn', 'tableRow', 'mergeTableCells'],
        },
        'language': 'es',
    },
}

# Sin subidas desde el editor: un documento legal no lleva imagenes, y una
# carpeta de subidas mas seria una carpeta mas que decidir en
# `deploy/media.htaccess` (invariante 13) para no ganar nada.
CKEDITOR_5_FILE_UPLOAD_PERMISSION = 'staff'

PQRS_NOTIFICATION_RECIPIENTS = [
    correo.strip()
    for correo in (os.getenv('PQRS_NOTIFICATION_RECIPIENTS') or '').split(',')
    if correo.strip()
]

# ChatGPT API Key
CHAT_GPT_API_KEY = os.getenv('CHAT_GPT_API_KEY')

# Block suspicious request settings
IP_BLOCKED_TIME_IN_MINUTES = int(os.getenv('IP_BLOCKED_TIME_IN_MINUTES'))

COMMON_ATTACK_TERMS = [
    term.strip() for term in os.getenv('COMMON_ATTACK_TERMS').split(',')
]

# Detector de rafagas de 404 (`apps/common/utils/scanning.py`). Los lee con
# `getattr(settings, ...)` y su propio defecto, asi que sin estas dos lineas
# ponerlas en el `.env` no hacia absolutamente nada --que es peor que no poder
# configurarlas, porque parece que si--.
SCAN_404_THRESHOLD = int(os.getenv('SCAN_404_THRESHOLD', 20))
SCAN_404_WINDOW_SECONDS = int(os.getenv('SCAN_404_WINDOW_SECONDS', 300))

# Base GeoLite2 para el pais de una IP bloqueada (`netintel.py`). Opcional: sin
# ella el campo se queda vacio y todo lo demas sigue igual. Por lo mismo que
# arriba, se lee aqui para que la variable de entorno signifique algo.
GEOIP_PATH = os.getenv('GEOIP_PATH', '')
