import hashlib


def generate_md5_or_sha256_hash(value: str, use_md5: bool = True) -> str:
    """
    Generate an MD5 or SHA256 hash for the given value.
    """
    if use_md5:
        return hashlib.md5(value.encode('utf-8')).hexdigest()
    else:
        return hashlib.sha256(value.encode('utf-8')).hexdigest()