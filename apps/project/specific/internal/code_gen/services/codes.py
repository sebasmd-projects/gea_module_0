# apps/project/specific/internal/code_gen/services/codes.py
"""
Composicion y validacion de los codigos emitidos por GEA.

Formato canonico del payload (los segmentos ausentes se omiten sin dejar
separadores dobles):

    NIT  TEXTO_LIBRE  INICIALES_SECUENCIA  HASH_B64  DDMMYYYY  CODIGO_ALEATORIO

Ejemplo:

    901.409.813-7 AEGIS_04829173 Xk3nQ9rT-1aBcD2e 25082026 K7M2PXQ9RT4H
"""

import re
import secrets
import unicodedata
from datetime import date
from typing import Iterable, List, Optional

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from ..constants import (BARCODE_ALLOWED_RE, BARCODE_FORBIDDEN_CHARS,
                         BARCODE_FORBIDDEN_SUBSTRINGS, BARCODE_MAX_LENGTH,
                         BARCODE_RECOMMENDED_MAX_LENGTH, COMPANY_NIT,
                         RANDOM_CODE_ALPHABET, RANDOM_CODE_DEFAULT_LENGTH,
                         RANDOM_CODE_MAX_LENGTH, RANDOM_CODE_MIN_LENGTH,
                         SEQUENCE_DEFAULT_NAME)

SEGMENT_SEPARATOR = ' '

URL_LIKE_RE = re.compile(r'(?i)\b(?:https?|ftp|mailto|data|file)\s*:')


def strip_accents(value: str) -> str:
    """Elimina tildes y diacriticos conservando el caracter base ASCII."""
    normalized = unicodedata.normalize('NFKD', value or '')
    return ''.join(char for char in normalized if not unicodedata.combining(char))


def sanitize_for_barcode(value: str) -> str:
    """
    Deja el texto en el subconjunto seguro de Code128.

    No se usa para validar: se usa para *sugerir* una version corregida del
    texto cuando el operador escribe algo no imprimible en barras.
    """
    cleaned = strip_accents(value).replace('_', '-')
    cleaned = ''.join(
        char if BARCODE_ALLOWED_RE.match(char) else ' '
        for char in cleaned
    )
    return re.sub(r'\s+', ' ', cleaned).strip()


def is_url_like(value: str) -> bool:
    """True si el texto parece una URL o un esquema de recurso."""
    return bool(URL_LIKE_RE.search(value or '')) or '://' in (value or '')


def validate_barcode_payload(value: str) -> str:
    """
    Valida que un texto pueda representarse como Code128 legible.

    Raises:
        ValidationError: si contiene caracteres no permitidos, parece una URL
        o excede la longitud maxima.

    Returns:
        str: el mismo texto, ya validado.
    """
    value = (value or '').strip()

    if not value:
        raise ValidationError(
            _('The barcode text cannot be empty.')
        )

    if is_url_like(value):
        raise ValidationError(
            _(
                'URLs and resource schemes (":", "://") cannot be encoded in a '
                'barcode. Use the QR code for links.'
            )
        )

    for forbidden in BARCODE_FORBIDDEN_SUBSTRINGS:
        if forbidden in value:
            raise ValidationError(
                _('The sequence "%(token)s" is not allowed in a barcode. '
                  'Use the QR code instead.') % {'token': forbidden}
            )

    offending = sorted(BARCODE_FORBIDDEN_CHARS.intersection(set(value)))
    if offending:
        raise ValidationError(
            _('These characters are not allowed in a barcode: %(chars)s. '
              'Use the QR code instead.') % {'chars': ' '.join(offending)}
        )

    if not BARCODE_ALLOWED_RE.match(value):
        raise ValidationError(
            _('Only letters, digits, spaces and the symbols . _ - are allowed '
              'in a barcode.')
        )

    if len(value) > BARCODE_MAX_LENGTH:
        raise ValidationError(
            _('The barcode text is too long (%(length)s characters). '
              'The maximum is %(maximum)s.') % {
                'length': len(value),
                'maximum': BARCODE_MAX_LENGTH,
            }
        )

    return value


def barcode_length_warning(value: str) -> Optional[str]:
    """Aviso no bloqueante cuando el simbolo va a quedar muy ancho."""
    if len(value or '') > BARCODE_RECOMMENDED_MAX_LENGTH:
        return str(
            _('The barcode has %(length)s characters; above %(maximum)s the '
              'symbol becomes very wide and harder to scan when printed.') % {
                'length': len(value),
                'maximum': BARCODE_RECOMMENDED_MAX_LENGTH,
            }
        )
    return None


def generate_random_code(length: int = RANDOM_CODE_DEFAULT_LENGTH) -> str:
    """
    Codigo unico aleatorio, alfabeto sin caracteres ambiguos (I, O, 0, 1).
    """
    length = int(length or RANDOM_CODE_DEFAULT_LENGTH)
    length = max(RANDOM_CODE_MIN_LENGTH, min(RANDOM_CODE_MAX_LENGTH, length))
    return ''.join(secrets.choice(RANDOM_CODE_ALPHABET) for _index in range(length))


def generate_unique_random_code(
    model,
    field: str = 'public_code',
    length: int = RANDOM_CODE_DEFAULT_LENGTH,
    attempts: int = 25
) -> str:
    """
    Codigo aleatorio garantizado unico contra un campo de un modelo.
    """
    for _attempt in range(attempts):
        candidate = generate_random_code(length)
        if not model.objects.filter(**{field: candidate}).exists():
            return candidate

    raise ValidationError(
        _('Could not generate a unique code. Try again.')
    )


def next_sequence(name: str = SEQUENCE_DEFAULT_NAME) -> str:
    """Siguiente valor de la secuencia autonoma (no consecutiva, no repetida)."""
    from ..models import CodeSequenceModel
    return CodeSequenceModel.next_value(name)


def derive_initials(reference: str, max_length: int = 6) -> str:
    """
    Deriva las iniciales del certificado a partir de la referencia.

    "AEGIS Special Edition" -> "ASE"; una sola palabra se conserva recortada.
    """
    cleaned = strip_accents(reference or '').upper()
    words = [word for word in re.split(r'[^A-Z0-9]+', cleaned) if word]

    if not words:
        return ''

    if len(words) == 1:
        return words[0][:max_length]

    return ''.join(word[0] for word in words)[:max_length]


def build_code_payload(
    *,
    include_nit: bool = False,
    custom_text: str = '',
    initials: str = '',
    sequence: str = '',
    hash_fragment: str = '',
    issue_date: Optional[date] = None,
    random_code: str = '',
    extra_segments: Optional[Iterable[str]] = None,
) -> str:
    """
    Une los segmentos en el orden canonico, omitiendo los vacios.

    Returns:
        str: el payload del codigo.
    """
    segments: List[str] = []

    if include_nit:
        segments.append(COMPANY_NIT)

    if custom_text:
        segments.append(custom_text.strip())

    identity = '_'.join(part for part in (initials, sequence) if part)
    if identity:
        segments.append(identity)

    if hash_fragment:
        segments.append(hash_fragment)

    if issue_date:
        segments.append(issue_date.strftime('%d%m%Y'))

    for extra in (extra_segments or ()):
        if extra:
            segments.append(str(extra).strip())

    if random_code:
        segments.append(random_code)

    return SEGMENT_SEPARATOR.join(segment for segment in segments if segment).strip()
