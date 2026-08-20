from __future__ import annotations

import hashlib
import hmac


def verify_github_signature(secret: str, body: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


def verify_gitlab_token(secret: str, header: str | None) -> bool:
    if not header:
        return False
    return hmac.compare_digest(secret, header)
