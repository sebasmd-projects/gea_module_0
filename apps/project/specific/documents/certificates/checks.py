# apps/project/specific/documents/certificates/checks.py
"""
System check de las claves de los emisores externos.

Una clave corta o adivinable en `GEA_EXTERNAL_ISSUERS` convierte el endpoint
de certificacion externa en una puerta abierta: quien la acierte emite
documentos con la firma de esta plataforma. Sin `DEBUG` es un error que
impide `runserver`/`migrate --check`; con `DEBUG` se deja pasar para no
estorbar en el portatil.
"""

from django.conf import settings
from django.core import checks

MIN_ISSUER_KEY_LENGTH = 32


@checks.register(checks.Tags.security)
def check_external_issuer_keys(app_configs=None, **kwargs):
    if settings.DEBUG:
        return []

    errors = []

    for slug, issuer in (
        getattr(settings, 'GEA_EXTERNAL_ISSUERS', None) or {}
    ).items():
        key = (issuer or {}).get('key') or ''

        # Sin clave = deshabilitado: no es un error.
        if key and len(key) < MIN_ISSUER_KEY_LENGTH:
            errors.append(checks.Error(
                f'The key of the external issuer "{slug}" is shorter than '
                f'{MIN_ISSUER_KEY_LENGTH} characters.',
                hint='Generate a longer one with '
                     '`python -c "import secrets; '
                     'print(secrets.token_urlsafe(48))"`.',
                id='gea.E001',
            ))

    return errors
