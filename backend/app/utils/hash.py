import hashlib


def sha256_text(text: str | bytes | None) -> str | None:
    if text is None:
        return None

    if isinstance(text, str):
        data = text.encode("utf-8", errors="ignore")
    else:
        data = text

    return hashlib.sha256(data).hexdigest()