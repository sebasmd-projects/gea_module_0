# app_core/settings_test.py
"""
Settings para ejecutar las pruebas.

El proyecto corre sobre MySQL en cPanel, donde el usuario de la aplicacion no
suele poder crear la base de datos ``test_...`` que Django necesita. Con estos
settings las pruebas van contra SQLite en memoria: se ejecutan en cualquier
sitio, sin tocar los datos reales y sin pedir privilegios.

    manage.py test <app> --settings=app_core.settings_test

``ATOMIC_REQUESTS`` se apaga porque envuelve cada peticion en una transaccion y
se lleva mal con las que abre el propio ``TestCase``. ``MEDIA_ROOT`` apunta a un
directorio temporal para que ninguna prueba escriba en el media de verdad.

El resto de este fichero existe para que **el resultado de la suite no dependa
del ``.env`` de quien la ejecuta**. ``settings.py`` decide por ``DJANGO_DEBUG``
si activa el endurecimiento de produccion; con un ``.env`` realista
(``DJANGO_DEBUG=False``) el cliente de pruebas se come un 301 a https en cada
peticion y decenas de pruebas fallan sin que nada este roto. Peor aun: pasan a
verde de nuevo cambiando una variable de entorno, que es justo lo que hace que
una suite deje de creerse. Aqui se fija lo que las pruebas necesitan.
"""

import tempfile

from app_core.settings import *  # noqa: F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

MEDIA_ROOT = tempfile.mkdtemp(prefix='gea_test_media_')
MEDIA_URL = '/media/'

ATOMIC_REQUESTS = False

# Que ninguna prueba mande correo de verdad ni llame a un servidor.
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

# Las URL permanentes (QR, registro de certificacion) no se derivan nunca del
# host de la peticion; en pruebas se fija un valor estable.
PUBLIC_BASE_URL = 'https://geausa.propensionesabogados.com'

# Hashear con Argon2 en cada prueba las hace lentas sin comprobar nada nuevo.
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# --- Independencia del .env ------------------------------------------------
# El cliente de pruebas habla http contra el host 'testserver'. Sin esto, con
# DJANGO_DEBUG=False cada peticion responde 301 antes de llegar a la vista.
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1']

# ManifestStaticFilesStorage exige un manifiesto de collectstatic; sin el,
# cualquier plantilla con {% static %} revienta al renderizar. En pruebas no
# aporta nada, y su ausencia no debe decidir si la suite pasa.
STORAGES = {
    **globals().get('STORAGES', {}),
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
}

# ``assets/signals.py`` instancia ``ChatGPTAPI()`` **al importar el modulo**, y
# el constructor revienta si la clave esta vacia: sin clave no arranca ni el
# proyecto ni la suite, aunque la traduccion automatica sea opcional. Aqui va
# un valor falso para que las pruebas no dependan de tener una clave real; no
# se llega a usar porque las pruebas no guardan textos sin traducir.
CHAT_GPT_API_KEY = 'test-key-not-a-real-openai-key'
