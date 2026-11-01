# apps/project/specific/documents/certificates/checks.py
"""
System check de la clave compartida de los emisores externos.

Los emisores son filas de ``ExternalIssuerModel`` y un check de Django **no
consulta la base de datos** (corre en ``migrate``, antes de que existan las
tablas). Lo que si vive en el entorno es ``SERVER_KEY``, la clave que
Propensiones comparte con pag y Vercel, y esa es la que se comprueba aqui: una
clave corta o adivinable convierte el endpoint de certificacion externa en una
puerta abierta, porque quien la acierte emite documentos con la firma de esta
plataforma. Las claves propias de cada emisor se validan al guardarlas
(``ExternalIssuerModel.set_key``).

Sin `DEBUG` es un error que impide `runserver`/`migrate --check`; con `DEBUG`
se deja pasar para no estorbar en el portatil.
"""

from django.conf import settings
from django.core import checks

MIN_ISSUER_KEY_LENGTH = 32


@checks.register(checks.Tags.security)
def check_external_issuer_keys(app_configs=None, **kwargs):
    errors = []

    legacy = getattr(settings, 'SERVER_KEY_LEGACY_VARS_IN_USE', None) or []
    if legacy:
        errors.append(checks.Warning(
            'The legacy environment variable %s is in use; define SERVER_KEY '
            '(same value in gea, pag and Vercel) and remove the old one.'
            % ', '.join(legacy),
            id='gea.W001',
        ))

    if settings.DEBUG:
        return errors

    key = getattr(settings, 'SERVER_KEY', '') or ''

    # Sin clave no es un error: los emisores que la usan quedan sin poder
    # autenticar, que es lo seguro.
    if key and len(key) < MIN_ISSUER_KEY_LENGTH:
        errors.append(checks.Error(
            f'SERVER_KEY (the key of the external issuers that use the '
            f'environment key) is shorter than {MIN_ISSUER_KEY_LENGTH} '
            f'characters.',
            hint='Generate a longer one with '
                 '`python -c "import secrets; '
                 'print(secrets.token_urlsafe(48))"`.',
            id='gea.E001',
        ))

    return errors
