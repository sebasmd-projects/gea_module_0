# apps/project/specific/internal/code_gen/constants.py
"""
Constantes del generador de codigos y del motor de certificacion documental.

Todo lo que sea configurable a nivel de negocio vive aqui para que el resto
de modulos (servicios, formularios, admin) no tenga valores magicos dispersos.
"""

import re

# ==========================================================
# Identidad de la firma
# ==========================================================
COMPANY_NIT = '901.409.813-7'

# ==========================================================
# Barcode (Code128)
# ==========================================================
# Code128 soporta ASCII 0-127, pero un codigo de barras legible por lectores
# comerciales y por humanos debe restringirse a un subconjunto seguro.
# Se prohiben explicitamente los caracteres tipicos de una URL.
BARCODE_ALLOWED_RE = re.compile(r'^[A-Za-z0-9 ._\-]+$')

BARCODE_FORBIDDEN_SUBSTRINGS = (
    '://',
    '//',
)

BARCODE_FORBIDDEN_CHARS = set('?&#%=+<>"\'\|^~`{}[]()@!$*,;:/')

# Longitud practica: por encima de esta cifra el simbolo se vuelve
# demasiado ancho para imprimirse en un certificado tamano carta.
BARCODE_RECOMMENDED_MAX_LENGTH = 48
BARCODE_MAX_LENGTH = 80

# ==========================================================
# Codigo unico aleatorio (tambien usado como public_code)
# ==========================================================
RANDOM_CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # sin I, O, 0, 1
RANDOM_CODE_DEFAULT_LENGTH = 12
RANDOM_CODE_MIN_LENGTH = 4
RANDOM_CODE_MAX_LENGTH = 32

# ==========================================================
# Secuencia autonoma (no consecutiva, no repetida)
# ==========================================================
# Permutacion multiplicativa modular: seq = (counter * A) mod M.
# gcd(A, M) == 1 => la funcion es biyectiva sobre [0, M), por lo que el
# valor nunca se repite dentro del ciclo y nunca es consecutivo.
SEQUENCE_MODULUS = 10 ** 8
SEQUENCE_MULTIPLIER = 62_774_333  # impar y no multiplo de 5 => coprimo con 10^8
SEQUENCE_PAD = 8
SEQUENCE_DEFAULT_NAME = 'default'

# ==========================================================
# Hash del documento embebido en el codigo
# ==========================================================
# base64 urlsafe sin padding del digest SHA-256 (32 bytes -> 43 chars).
# Se trunca para mantener el barcode legible; el hash completo queda
# almacenado y visible en la pagina de verificacion.
HASH_B64_DEFAULT_LENGTH = 16
HASH_B64_MIN_LENGTH = 8
HASH_B64_MAX_LENGTH = 43

# ==========================================================
# Formatos aceptados
# ==========================================================
# Certificacion completa (estampado + marca de agua + copia distribuible).
CERTIFIABLE_EXTENSIONS = ('.pdf',)
CERTIFIABLE_CONTENT_TYPES = ('application/pdf',)

# Verificacion por archivo: se acepta cualquier PDF y ademas cualquier binario
# para el cotejo por hash exacto (util si el usuario renombra el archivo).
VERIFIABLE_EXTENSIONS = ('.pdf',)

MAX_UPLOAD_BYTES = 60 * 1024 * 1024  # 60 MB

# ==========================================================
# Marca de agua imperceptible
# ==========================================================
WATERMARK_MAGIC = 'GEAWM1'
WATERMARK_XOBJECT_NAME = '/GEAWMK'
WATERMARK_INFO_KEY = '/GEAWatermark'
WATERMARK_HMAC_LENGTH = 16

# ==========================================================
# Estampado por defecto (puntos PostScript, 72 pt = 1 pulgada)
# ==========================================================
DEFAULT_QR_SIZE_PT = 84.0
DEFAULT_BARCODE_WIDTH_PT = 216.0
DEFAULT_BARCODE_HEIGHT_PT = 54.0
DEFAULT_MARGIN_PT = 28.0
