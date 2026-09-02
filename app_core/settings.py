import os
from datetime import date
from datetime import timedelta
from pathlib import Path

from django.utils.translation import gettext_lazy as _
from dotenv import load_dotenv
from import_export.formats.base_formats import CSV, HTML, JSON, TSV, XLS, XLSX

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# Registro de la aplicacion.
#
# Antes esto era un `logging.basicConfig(filename='stderr.log', ...)` con ruta
# **relativa**, y eso tenia dos problemas que solo se notan cuando hace falta
# el log, que es el peor momento para descubrirlos:
#
# 1. La ruta relativa depende del directorio de trabajo del proceso, que bajo
#    Passenger en cPanel no es necesariamente la raiz del proyecto. El fichero
#    que uno abre para mirar podia no ser el que la aplicacion escribia.
# 2. `basicConfig` solo toca el logger raiz. Django configura los suyos por su
#    cuenta, y `django.request` --el que registra los errores 500-- acaba
#    dependiendo de que la propagacion siga intacta. Bastaba con que algo
#    ajustara el logger `django` para que los errores dejaran de aparecer.
#
# Ahora la ruta es absoluta y la configuracion es explicita: los errores de
# peticion se escriben siempre, y se ve de que peticion venian.
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
            # `WatchedFileHandler` y no `FileHandler`, y no es un detalle:
            # es lo que hace posible rotar el log.
            #
            # Rotar es renombrar el fichero. En Linux, renombrar no afecta a
            # quien lo tiene abierto: el descriptor sigue apuntando al mismo
            # inodo, ahora con otro nombre. Y aqui la aplicacion corre en
            # varios procesos, cada uno con el suyo abierto desde que arranco.
            # Con `FileHandler`, tras rotar todos los workers seguirian
            # escribiendo en `stderr_old_6.log`, el `stderr.log` nuevo se
            # quedaria vacio para siempre, y el "viejo" seria el que crece.
            # Sin error y sin aviso: no se nota hasta que hace falta el log.
            #
            # `WatchedFileHandler` comprueba antes de escribir si el fichero
            # que tiene abierto sigue siendo el que hay en esa ruta, y si no,
            # lo reabre. Esta pensado exactamente para que rote otro.
            #
            # Y rota otro --`manage.py rotate_logs` desde el cron-- en vez de
            # `RotatingFileHandler`, que rota el proceso que escribe: con
            # varios workers, dos pueden cruzar el renombrado y partir o
            # perder el log. Ver `apps/common/utils/logs.py`.
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
        # Los 500 y los avisos de peticion. Sin `propagate: False` se
        # escribirian dos veces: aqui y otra vez por la raiz.
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
    # 'betterforms' estaba aqui sin que nada lo usara.
    #
    # Lo arrastraba `django-two-factor-auth`, que hasta la 1.15 lo necesitaba
    # para sus formularios. Desde entonces ya no, pero el paquete se quedo
    # declarado como dependencia directa y en INSTALLED_APPS. Nadie del
    # proyecto lo importa, y ningun paquete instalado tampoco -- comprobado
    # sobre el entorno, no sobre la documentacion.
    #
    # Costaba un aviso en cada arranque, en cada comando y en cada linea del
    # log: su `__init__` llama a `pkg_resources`, que esta en retirada. Un
    # aviso permanente que no significa nada es peor que ninguno, porque
    # ensena a no leerlos.
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

# import_export
IMPORT_EXPORT_FORMATS = [CSV, HTML, JSON, TSV, XLS, XLSX]

LOGIN_URL = 'two_factor:login'

LOGIN_REDIRECT_URL = 'core:index'

# --- Los códigos de seis cifras que se mandan por correo --------------------
# Hay dos: el que deja entrar en la plataforma y el que abre la consulta
# pública de un certificado. Duran lo mismo --quince minutos, lo bastante para
# ir a buscar el correo a la carpeta de no deseado-- y cada uno tiene su
# variable, porque son dos decisiones distintas aunque hoy coincidan.
LOGIN_OTP_TTL_MINUTES = int(os.getenv('LOGIN_OTP_TTL_MINUTES', 15))

OTP_TTL_MINUTES = int(os.getenv('OTP_TTL_MINUTES', 15))

# A quién escribir si a alguien le llega un código que no ha pedido, que es la
# señal de que otro está intentando entrar en su cuenta. **Una sola variable
# para los dos correos**: son el mismo mensaje con distinto motivo, y dos
# ajustes para la misma dirección acaban divergiendo el día que se cambie uno.
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

# La cookie de sesion no se lee desde JavaScript. Django ya lo trae asi por
# defecto; se fija explicito porque es de las cosas que se desactivan sin
# querer al depurar algo y nadie vuelve a mirarlas.
SESSION_COOKIE_HTTPONLY = True

# `Lax` y no `None`: la cookie no viaja en peticiones cruzadas de otros
# sitios, que es la mitad de la defensa contra CSRF cuando un token se
# escapa. No se pone `Strict` porque romperia volver a la plataforma desde un
# enlace de correo -- el de recuperacion de contrasena, por ejemplo -- y una
# sesion que se cae al llegar desde el correo se acaba resolviendo aflojando
# esto del todo.
SESSION_COOKIE_SAMESITE = 'Lax'

# Cuanto puede pesar un envio, aparte de los ficheros. Django trae 2,5 MB por
# defecto; se fija explicito por lo mismo que arriba.
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# Cuantos ficheros admite un solo envio. Sin tope, una peticion con miles de
# ficheros abre miles de descriptores antes de que nadie valide nada.
DATA_UPLOAD_MAX_NUMBER_FILES = 20

ROSETTA_SHOW_AT_ADMIN_PANEL = True

# Base absoluta del sitio, usada cuando se generan URLs (QR de certificacion)
# fuera del ciclo de una peticion, por ejemplo desde una accion del admin.
# ==========================================================
# Cache
# ==========================================================
# Sin CACHES definido Django usa LocMemCache, que es **por proceso**. Los
# limites de tasa del OTP publico (certificates/mixins.py), el codigo de
# registro de compradores y el cupo de recuperacion de contrasena viven en
# cache: con N workers los limites son N veces mas laxos y se reinician en
# cada despliegue. Es el bypass mas facil de la unica superficie no
# autenticada que tiene la plataforma.
#
# El hosting (cPanel / Conexcol) no permite levantar Redis, asi que la salida
# es un Redis en un VPS propio. Instrucciones de montaje: deploy/REDIS.md.
#
# Sin REDIS_URL se mantiene el comportamiento de siempre, para que un entorno
# de desarrollo o la propia suite no dependan de tener Redis delante.
REDIS_URL = os.getenv('REDIS_URL', '').strip()

# El broker de la cola de tareas, si algun dia la hay. **Es otra URL, no la de
# arriba**, y esa es toda la cuestion: el usuario `gea` de la cache esta acotado
# a `~gea:*` y a `+@read +@write +@keyspace`, y un broker necesita sus propios
# nombres de clave, PING, pub/sub y transacciones. Con las credenciales de la
# cache, un broker responde NOPERM a las cinco.
#
# Va aparte tambien en la base de datos (`/1`), aunque quien de verdad aisla es
# el patron de claves: las ACL de Redis no se acotan por base de datos, asi que
# un usuario con `~*` conectado a la base 0 leeria las claves de la cache.
#
# Vacio mientras no se monte la cola. `manage.py check_workers` lo usa para
# comprobar si el Redis serviria de broker; sin el, esa comprobacion no puede
# dar verde por mucho que la ACL este bien. Ver deploy/REDIS.md, paso 9.
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', '').strip()

if REDIS_URL:
    CACHES = {
        'default': {
            # django-redis y no el backend de Django a proposito: es el unico
            # que trae IGNORE_EXCEPTIONS. El Redis vive en otra maquina y el
            # trafico sale a internet, asi que un corte de red es cuestion de
            # tiempo. Con el backend nativo, ese corte convierte en error 500
            # el login, el OTP publico y la recuperacion de contrasena --
            # justo las paginas que mas importa que sigan de pie.
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': REDIS_URL,
            'TIMEOUT': 300,
            'KEY_PREFIX': os.getenv('REDIS_KEY_PREFIX', 'gea'),
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',

                # Un Redis caido degrada a "sin cache", no tumba el sitio.
                #
                # Ojo con lo que significa esto exactamente, porque es
                # contraintuitivo y ya costo un fallo: `django-redis` no
                # **lanza** la excepcion, la **devuelve como `None`**. Un
                # `try/except` alrededor de una operacion de cache por tanto
                # no se entera de nada, y `cache.get(k) or 0` da `0`, que es
                # menos que cualquier limite. Los contadores de tasa dejaban
                # de aplicarse en silencio: ni excepcion, ni log, ni sintoma.
                #
                # Ya no. Todos pasan por `apps.common.utils.throttling`, que
                # detecta la averia por el valor que devuelve `incr` --entero
                # si la cache vive, `None` si no-- y decide **por cupo**:
                # cerrado donde el limite es el control (codigos publicos,
                # envio de correos a terceros), abierto y con la razon escrita
                # donde no lo es. Lee ese modulo antes de tocar esta linea.
                'IGNORE_EXCEPTIONS': True,

                # Un VPS que no responde no puede quedarse colgando la
                # peticion: con ATOMIC_REQUESTS eso es una transaccion abierta.
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
    #
    # Cada 15 minutos y no cada hora porque nadie avisa de que una prueba haya
    # madurado: preguntar mas a menudo es lo unico que acorta el tiempo entre
    # que el bloque existe y que la pagina lo muestra. No sale caro: sin
    # anclajes pendientes el comando termina en una consulta, sin tocar la
    # red, asi que cuando todo esta confirmado la tarea se apaga sola.
    ('*/15 * * * *', 'django.core.management.call_command',
     ['upgrade_ots_anchors']),
    ('0 19 * * *', 'apps.common.utils.cron.generate_and_send_gea_code'),
    ('*/3 * * * *', 'apps.common.utils.cron.warm_gea_app'),
    # Rota el log al pasar de 3 MB. Cada hora y no una vez por semana: la
    # revision es un `stat` --sin llegar al tope no hace absolutamente nada--
    # y con cadencia semanal un dia malo deja el fichero en decenas de megas
    # antes de que a nadie le toque mirarlo, con lo que el tope de 3 MB no
    # significaria nada. Lo que hace que esto funcione con varios workers
    # esta en LOGGING: el handler es WatchedFileHandler.
    ('0 * * * *', 'django.core.management.call_command', ['rotate_logs']),
]

# --- Documentos legales: version y fecha de vigencia -------------------
#
# Van aqui y no dentro de cada plantilla porque el articulo 18 de la propia
# politica obliga a publicar la fecha de entrada en vigor de cada
# modificacion, y sin version no se puede demostrar que texto acepto alguien
# el dia que se registro. Repartidas por las plantillas, actualizar una y
# olvidar otra es cuestion de tiempo.
LEGAL_DOCUMENT_VERSIONS = {
    'terms': {'version': '1.0.0-borrador', 'date': date(2026, 9, 1)},
    'data_policy': {'version': '1.0.0-borrador', 'date': date(2026, 9, 1)},
    'privacy': {'version': '1.0.0-borrador', 'date': date(2026, 9, 1)},
    'cookies': {'version': '1.0.0-borrador', 'date': date(2026, 9, 1)},
}

# A quien avisar cuando entra una PQRS. Sin destinatarios no se avisa a nadie
# y la solicitud se queda esperando en el panel -- con su plazo corriendo.
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
