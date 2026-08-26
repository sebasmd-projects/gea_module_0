# apps/project/specific/documents/certificates/constants.py
"""Constantes de la verificacion publica de certificados."""

# Longitud del codigo publico de un documento certificado.
# Historicamente eran 4 caracteres; los documentos emitidos por el motor de
# certificacion usan 12, que es tambien el codigo aleatorio incrustado en el
# codigo de barras.
DOCUMENT_PUBLIC_CODE_LENGTH = 12

# Longitud del codigo publico de un certificado de persona.
USER_PUBLIC_CODE_LENGTH = 4

# Identificadores aceptados en el formulario publico de verificacion.
IDENTIFIER_MIN_LENGTH = 4
IDENTIFIER_MAX_LENGTH = 36

# Verificacion por archivo.
MAX_VERIFICATION_UPLOAD_BYTES = 60 * 1024 * 1024  # 60 MB
VERIFICATION_UPLOAD_EXTENSIONS = ('.pdf',)

# Clave de sesion donde se deja el resultado del cotejo por archivo para
# pintarlo en la pagina de detalle.
FILE_MATCH_SESSION_KEY = 'document_file_match'
