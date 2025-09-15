import hashlib


def sha256_hex(data: str | bytes) -> str:
    """
    Devuelve un SHA-256 en hex.
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()