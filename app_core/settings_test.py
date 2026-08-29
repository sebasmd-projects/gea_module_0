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
