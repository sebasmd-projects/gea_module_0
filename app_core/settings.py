import logging
import os
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
    SECURE_HSTS_SECONDS = 31536000 # 1 year
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    X_FRAME_OPTIONS = 'DENY'
    if ',' in os.getenv('DJANGO_ALLOWED_HOSTS'):
        ALLOWED_HOSTS = os.getenv('DJANGO_ALLOWED_HOSTS').split(',')
    else:
        ALLOWED_HOSTS = [os.getenv('DJANGO_ALLOWED_HOSTS')]


DJANGO_APPS = [
    'django.contrib.admin',
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
    'drf_yasg',
    'encrypted_model_fields',
    'formtools',
    'import_export',
    'parler',
    'rest_framework',
    'rest_framework.authtoken',
    'rest_framework_simplejwt',
    'rosetta',
    'two_factor',
]

COMMON_APPS = [
    'apps.common.core',
    'apps.common.utils',
]

PROJECT_COMMON_APPS = [
    'apps.project.common.account',
    'apps.project.common.notifications',
    'apps.project.common.users',
]

PROJECT_ASSETS_MANAGEMENT_APPS = [
    'apps.project.specific.assets_management.assets',
    'apps.project.specific.assets_management.assets_location',
    'apps.project.specific.assets_management.buyers'
]

PROJECT_INTERNAL_APPS = [

]

PROJECT_DOCUMENTS_APPS = [
    'apps.project.specific.documents.pol',
]

ALL_CUSTOM_APPS = PROJECT_ASSETS_MANAGEMENT_APPS + PROJECT_COMMON_APPS + \
    PROJECT_INTERNAL_APPS + PROJECT_DOCUMENTS_APPS + COMMON_APPS

INSTALLED_APPS = ALL_CUSTOM_APPS + THIRD_PARTY_APPS + DJANGO_APPS

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

TIME_ZONE = 'America/Bogota'

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
]

MIDDLEWARE_NOT_INCLUDE = [os.getenv('MIDDLEWARE_NOT_INCLUDE')]

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

DATABASES = {
    'default': {
        'CONN_MAX_AGE': int(os.getenv('DB_CONN_MAX_AGE')),
        'ENGINE': os.getenv('DB_ENGINE'),
        'NAME': os.getenv('DB_NAME'),
        'USER': os.getenv('DB_USER'),
        'PASSWORD': os.getenv('DB_PASSWORD'),
        'HOST': os.getenv('DB_HOST'),
        'PORT': int(os.getenv('DB_PORT')),
        'CHARSET': os.getenv('DB_CHARSET'),
        'ATOMIC_REQUESTS': True,
    }
}

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
    f'{UTILS_PATH}.backend.EmailOrUsernameModelBackend',
    'axes.backends.AxesStandaloneBackend',
    'django.contrib.auth.backends.ModelBackend',
]

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.BasicAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend'
    ],
}

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
]

SESSION_EXPIRE_AT_BROWSER_CLOSE = False

SESSION_COOKIE_AGE = 7200

ROSETTA_SHOW_AT_ADMIN_PANEL = True

STATIC_URL = os.getenv('DJANGO_STATIC_URL')

STATIC_ROOT = str(os.getenv('DJANGO_STATIC_ROOT'))

MEDIA_URL = os.getenv('DJANGO_MEDIA_URL')

MEDIA_ROOT = str(os.getenv('DJANGO_MEDIA_ROOT'))

STATICFILES_DIRS = [str(BASE_DIR / 'public' / 'staticfiles')]

STATICFILES_FINDERS = (
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
    'compressor.finders.CompressorFinder',
)

if bool(os.getenv('DJANGO_EMAIL_USE_SSL')):
    EMAIL_USE_SSL = True
    EMAIL_USE_TLS = False
else:
    EMAIL_USE_SSL = False
    EMAIL_USE_TLS = True

DEFAULT_FROM_EMAIL = os.getenv('DJANGO_EMAIL_DEFAULT_FROM_EMAIL')
EMAIL_BACKEND = os.getenv('DJANGO_EMAIL_BACKEND')
EMAIL_HOST = os.getenv('DJANGO_EMAIL_HOST')
EMAIL_HOST_PASSWORD = os.getenv('DJANGO_EMAIL_HOST_PASSWORD')
EMAIL_HOST_USER = os.getenv('DJANGO_EMAIL_HOST_USER')
EMAIL_PORT = int(os.getenv('DJANGO_EMAIL_PORT'))


if ',' in os.getenv('GEA_DAILY_CODE_BUYER_RECIPIENTS'):
    GEA_DAILY_CODE_BUYER_RECIPIENTS = os.getenv('GEA_DAILY_CODE_BUYER_RECIPIENTS').split(',')
else:
    GEA_DAILY_CODE_BUYER_RECIPIENTS = [os.getenv('GEA_DAILY_CODE_BUYER_RECIPIENTS')]


if ',' in os.getenv('GEA_DAILY_CODE_GENERAL_RECIPIENTS'):
    GEA_DAILY_CODE_GENERAL_RECIPIENTS = os.getenv('GEA_DAILY_CODE_GENERAL_RECIPIENTS').split(',')
else:
    GEA_DAILY_CODE_GENERAL_RECIPIENTS = [os.getenv('GEA_DAILY_CODE_GENERAL_RECIPIENTS')]


CORS_ALLOWED_ORIGINS = list(os.getenv('CORS_ALLOWED_ORIGINS').split(','))

YASG_DEFAULT_EMAIL = os.getenv('YASG_DEFAULT_EMAIL')
YASG_TERMS_OF_SERVICE = os.getenv('YASG_TERMS_OF_SERVICE')

FIELD_ENCRYPTION_KEY = os.getenv('FIELD_ENCRYPTION_KEY')

DATA_UPLOAD_MAX_NUMBER_FIELDS = 15000

# Cron jobs
CRONJOBS = [
    ('0 1 * * *', 'apps.common.utils.cron.generate_and_send_gea_code')
]

# ChatGPT API Key
CHAT_GPT_API_KEY = os.getenv('CHAT_GPT_API_KEY')

# Block suspicious request settings
IP_BLOCKED_TIME_IN_MINUTES = int(os.getenv('IP_BLOCKED_TIME_IN_MINUTES'))

COMMON_ATTACK_TERMS = [
    term.strip() for term in os.getenv('COMMON_ATTACK_TERMS').split(',')
]

