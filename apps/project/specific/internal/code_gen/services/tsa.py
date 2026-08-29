# apps/project/specific/internal/code_gen/services/tsa.py
"""
Sellado de tiempo RFC 3161.

Lo unico que el sistema no puede probar por si mismo es **la fecha**:
``certified_at`` lo afirma la propia plataforma. Una TSA es un tercero que
firma «este hash existia a esta hora», y su token es verificable por cualquiera
con herramientas estandar (``openssl ts -verify``).

Que sale de aqui hacia fuera: **solo el hash**. Nunca el documento, ni el
payload, ni nada legible. La TSA no ve lo que se sella.

Aviso importante sobre el proveedor
-----------------------------------
Una TSA gratuita (FreeTSA y similares) es tecnicamente identica pero **no
tiene peso legal**. Para que «fuerza probatoria» signifique algo hace falta un
proveedor cualificado (QTSP de la lista eIDAS) o acreditado ONAC en Colombia.
El codigo es agnostico: se configura con ``CERTIFICATION_TSA_URL``.
"""

import hashlib
import logging
import os
from typing import Optional

from django.conf import settings
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)

CONTENT_TYPE_REQUEST = 'application/timestamp-query'
CONTENT_TYPE_RESPONSE = 'application/timestamp-reply'

DEFAULT_TIMEOUT = 20

# Estados de la respuesta PKIStatus (RFC 3161 sec. 2.4.2). asn1crypto los
# devuelve por nombre, no por numero, asi que se aceptan ambas formas.
GRANTED = (0, 1, 'granted', 'granted_with_mods')


class TSAError(Exception):
    """El sellado de tiempo no se pudo completar."""


def _tst_info(token):
    """
    Extrae el TSTInfo de un token, venga como venga.

    asn1crypto parsea solo el OCTET STRING cuando reconoce el tipo de
    contenido, asi que ``.native`` puede devolver ya un diccionario en vez de
    los bytes. Se prueba primero la forma parseada y se cae a los bytes.
    """
    from asn1crypto import tsp

    content = token['content']['encap_content_info']['content']

    parsed = getattr(content, 'parsed', None)
    if isinstance(parsed, tsp.TSTInfo):
        return parsed

    raw = content.native
    if isinstance(raw, (bytes, bytearray)):
        return tsp.TSTInfo.load(bytes(raw))

    raise TSAError(str(_('The timestamp token has no readable TSTInfo.')))


def tsa_url() -> str:
    return str(getattr(settings, 'CERTIFICATION_TSA_URL', '') or '').strip()


def is_configured() -> bool:
    return bool(tsa_url())


def build_request(digest_hex: str, *, nonce: bool = True,
                  request_certificate: bool = True) -> bytes:
    """
    Construye la peticion DER de sello de tiempo para un SHA-256.

    Parameters:
        digest_hex (str): el hash a sellar, en hexadecimal.
        nonce (bool): incluye un valor aleatorio que la TSA debe devolver;
            impide que alguien reproduzca una respuesta antigua.
        request_certificate (bool): pide que el token traiga el certificado
            de la TSA, para poder verificarlo sin descargarlo aparte.
    """
    from asn1crypto import tsp

    try:
        digest = bytes.fromhex(digest_hex)
    except ValueError as error:
        raise TSAError(str(_('The hash is not valid hexadecimal.'))) from error

    if len(digest) != 32:
        raise TSAError(str(_('Only SHA-256 digests are supported.')))

    request = {
        'version': 'v1',
        'message_imprint': {
            'hash_algorithm': {'algorithm': 'sha256'},
            'hashed_message': digest,
        },
        'cert_req': request_certificate,
    }

    if nonce:
        request['nonce'] = int.from_bytes(os.urandom(16), 'big')

    return tsp.TimeStampReq(request).dump()


def parse_response(der: bytes, *, expected_digest_hex: Optional[str] = None) -> dict:
    """
    Valida la respuesta de la TSA y extrae lo util.

    No comprueba la cadena de confianza del certificado de la TSA — eso exige
    un almacen de raices y politica propia. Si comprueba lo que decide si el
    token sirve para este documento: que la TSA concedio el sello y que el
    hash sellado es el nuestro.

    Returns:
        dict: ``{'token': bytes, 'gen_time': datetime, 'serial': int,
        'policy': str, 'tsa_name': str, 'digest': str}``
    """
    from asn1crypto import tsp

    try:
        response = tsp.TimeStampResp.load(der)
    except Exception as error:
        raise TSAError(
            str(_('The timestamp authority returned an unreadable response.'))
        ) from error

    status_info = response['status']
    status = status_info['status'].native

    if status not in GRANTED:
        reason = ''
        try:
            reason = ', '.join(
                str(item) for item in (status_info['fail_info'].native or [])
            )
        except Exception:
            pass

        raise TSAError(
            str(
                _('The timestamp authority refused the request '
                  '(status %(status)s). %(reason)s')
                % {'status': status, 'reason': reason}
            )
        )

    token = response['time_stamp_token']

    try:
        info = _tst_info(token)
    except TSAError:
        raise
    except Exception as error:
        raise TSAError(
            str(_('The timestamp token could not be parsed.'))
        ) from error

    imprint = info['message_imprint']['hashed_message'].native
    digest_hex = imprint.hex()

    if expected_digest_hex and digest_hex.lower() != expected_digest_hex.lower():
        # Un token de otro documento no acredita nada sobre este.
        raise TSAError(
            str(_('The timestamp covers a different hash than the one sent.'))
        )

    tsa_name = ''
    try:
        if info['tsa'].native:
            tsa_name = str(info['tsa'].native)
    except Exception:
        pass

    return {
        'token': token.dump(),
        'gen_time': info['gen_time'].native,
        'serial': int(info['serial_number'].native),
        'policy': str(info['policy'].native),
        'tsa_name': tsa_name,
        'digest': digest_hex,
    }


def request_timestamp(digest_hex: str, *, url: Optional[str] = None,
                      timeout: int = DEFAULT_TIMEOUT) -> dict:
    """
    Pide un sello de tiempo a la TSA configurada.

    Raises:
        TSAError: si no hay TSA configurada, si la red falla o si la respuesta
        no acredita nuestro hash.
    """
    import requests

    endpoint = (url or tsa_url())

    if not endpoint:
        raise TSAError(
            str(_('No timestamp authority is configured '
                  '(CERTIFICATION_TSA_URL).'))
        )

    payload = build_request(digest_hex)

    headers = {
        'Content-Type': CONTENT_TYPE_REQUEST,
        'Accept': CONTENT_TYPE_RESPONSE,
    }

    auth = None
    username = getattr(settings, 'CERTIFICATION_TSA_USERNAME', '')
    password = getattr(settings, 'CERTIFICATION_TSA_PASSWORD', '')

    if username:
        auth = (username, password)

    try:
        response = requests.post(
            endpoint,
            data=payload,
            headers=headers,
            timeout=timeout,
            auth=auth,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        raise TSAError(
            str(
                _('Could not reach the timestamp authority: %(error)s')
                % {'error': error}
            )
        ) from error

    parsed = parse_response(response.content, expected_digest_hex=digest_hex)
    parsed['url'] = endpoint

    return parsed


def verify_token(token_der: bytes, digest_hex: str) -> dict:
    """
    Comprueba un token guardado contra el hash que deberia acreditar.

    Es la verificacion que puede hacer la plataforma sin salir a la red. Un
    tercero puede llegar mas lejos con ``openssl ts -verify``, validando ademas
    la cadena del certificado de la TSA contra su propio almacen de raices.

    Returns:
        dict: ``{'valid': bool, 'detail': str, ...}``
    """
    from asn1crypto import cms, tsp

    result = {'valid': False, 'detail': '', 'gen_time': None, 'digest': None}

    if not token_der:
        result['detail'] = str(_('There is no timestamp token stored.'))
        return result

    try:
        token = cms.ContentInfo.load(bytes(token_der))
        info = _tst_info(token)
    except Exception:
        result['detail'] = str(_('The stored token could not be parsed.'))
        return result

    stamped = info['message_imprint']['hashed_message'].native.hex()

    result['digest'] = stamped
    result['gen_time'] = info['gen_time'].native
    result['serial'] = int(info['serial_number'].native)

    if stamped.lower() != (digest_hex or '').lower():
        result['detail'] = str(
            _('The token covers a different hash: it does not attest this '
              'summary.')
        )
        return result

    result['valid'] = True
    result['detail'] = str(
        _('The token attests this hash existed at the time it states.')
    )

    return result
