# apps/common/utils/backup_crypto.py
"""
Cifrado de los respaldos, para que el fichero descargado no se lea solo.

El problema que resuelve
------------------------
``manage.py db_backup`` produce volcados JSON con ``dumpdata``, y ``dumpdata``
serializa el **valor de Python** de cada campo. En los campos de
``django-encrypted-model-fields`` ese valor es el ya descifrado: el correo, el
teléfono, la fecha de nacimiento y el número de pasaporte salen en claro al
fichero. Comprobado.

O sea que el respaldo deshacía el cifrado de campo. `FIELD_ENCRYPTION_KEY`
protege la base de datos contra un volcado robado; el volcado de al lado, sin
llave, es exactamente ese volcado robado servido en bandeja -- y encima suele
acabar en un portátil, en un adjunto de correo o en una carpeta compartida.

Qué se hace
-----------
El JSON se cifra con **Fernet** (AES-128-CBC y HMAC-SHA256, autenticado: si
alguien altera un byte, descifrar falla en vez de devolver basura) con una
clave derivada de una contraseña por **scrypt**. Sin la contraseña el fichero
no se lee, y con ella se recupera con ``manage.py db_restore_open``.

Por qué scrypt y no la contraseña a pelo
----------------------------------------
Una contraseña que teclea una persona no tiene 256 bits de entropía. Derivarla
con una función **lenta y con coste de memoria** es lo que hace que probar el
diccionario cueste; con un hash rápido, el fichero cifrado se abre a fuerza
bruta en un rato. Los parámetros van escritos **dentro** del fichero, así que
subirlos más adelante no invalida los respaldos ya hechos.

Por qué la contraseña no se pasa por la línea de comandos
---------------------------------------------------------
Porque acabaría en el historial del intérprete y en la salida de ``ps``, donde
la ve cualquiera con una sesión en la misma máquina. Se lee de una variable de
entorno o de un fichero, y de ningún otro sitio.
"""

import base64
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

#: Marca de formato. Va en la primera línea para que un fichero cifrado se
#: reconozca de un vistazo y para poder cambiar el formato sin adivinar.
MAGIC = b'GEABACKUP1'

#: Parámetros de scrypt. `n` es el coste; 2**15 tarda una fracción de segundo
#: en un servidor y convierte un diccionario en algo caro. Se guardan dentro
#: del fichero: subirlos mañana no invalida lo cifrado ayer.
SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1
SALT_BYTES = 16

#: De dónde sale la contraseña. Nunca de un argumento de la orden.
PASSPHRASE_ENV = 'GEA_BACKUP_PASSPHRASE'


class BackupCryptoError(Exception):
    """No se pudo cifrar o descifrar."""


def derive_key(passphrase: str, salt: bytes, *, n=SCRYPT_N, r=SCRYPT_R,
               p=SCRYPT_P) -> bytes:
    """La clave Fernet derivada de una contraseña y su sal."""
    kdf = Scrypt(salt=salt, length=32, n=n, r=r, p=p)

    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode('utf-8')))


def encrypt(payload: bytes, passphrase: str) -> bytes:
    """
    Cifra el volcado y devuelve el fichero completo, cabecera incluida.

    El formato es de texto en su cabecera a propósito: quien se encuentre el
    fichero dentro de tres años tiene que poder saber qué es y con qué se abre
    sin leer este módulo.
    """
    if not passphrase:
        raise BackupCryptoError('no hay contraseña con la que cifrar')

    salt = os.urandom(SALT_BYTES)
    token = Fernet(derive_key(passphrase, salt)).encrypt(payload)

    header = b'\n'.join([
        MAGIC,
        f'scrypt n={SCRYPT_N} r={SCRYPT_R} p={SCRYPT_P}'.encode(),
        base64.b64encode(salt),
        b'',
    ])

    return header + token


def decrypt(blob: bytes, passphrase: str) -> bytes:
    """
    Devuelve el JSON original, o levanta ``BackupCryptoError``.

    Fernet está autenticado, así que una contraseña equivocada y un fichero
    manipulado dan el mismo error -- y eso es lo correcto: descifrar mal no
    puede devolver un JSON que parezca válido.
    """
    try:
        magic, params, salt_b64, rest = blob.split(b'\n', 3)
    except ValueError:
        raise BackupCryptoError('el fichero no tiene la cabecera esperada')

    if magic.strip() != MAGIC:
        raise BackupCryptoError(
            'el fichero no es un respaldo cifrado de esta plataforma')

    numbers = dict(
        piece.split('=') for piece in params.decode().split()[1:]
    )

    try:
        key = derive_key(
            passphrase,
            base64.b64decode(salt_b64),
            n=int(numbers['n']), r=int(numbers['r']), p=int(numbers['p']),
        )

        return Fernet(key).decrypt(rest)
    except (InvalidToken, KeyError, ValueError):
        raise BackupCryptoError(
            'no se pudo descifrar: la contraseña no es esa, o el fichero está '
            'alterado'
        )


def passphrase_from(path=None):
    """
    La contraseña, de la variable de entorno o de un fichero.

    De la línea de comandos no, y esa omisión es deliberada: un argumento
    acaba en el historial del intérprete y en la salida de ``ps``, donde lo ve
    cualquiera con una sesión en la misma máquina.
    """
    if path:
        with open(path, 'r', encoding='utf-8') as handle:
            return handle.read().strip()

    return (os.environ.get(PASSPHRASE_ENV) or '').strip()
