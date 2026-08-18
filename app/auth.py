from __future__ import annotations

import base64
import hashlib
import hmac
import os


def hash_password(pw: str, *, salt: bytes | None = None, iterations: int = 200_000) -> str:
    salt = salt if salt is not None else os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, iterations)
    return (f"pbkdf2_sha256${iterations}${base64.b64encode(salt).decode()}"
            f"${base64.b64encode(dk).decode()}")


def verify_password(pw: str, stored: str) -> bool:
    try:
        algo, iters, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, int(iters))
        return hmac.compare_digest(base64.b64encode(dk).decode(), hash_b64)
    except Exception:
        return False


def make_session_token(user: str, secret: str) -> str:
    sig = hmac.new(secret.encode(), user.encode(), hashlib.sha256).hexdigest()
    return f"{user}:{sig}"


def verify_session_token(token: str | None, secret: str) -> str | None:
    if not token or ":" not in token:
        return None
    user, sig = token.rsplit(":", 1)
    expected = hmac.new(secret.encode(), user.encode(), hashlib.sha256).hexdigest()
    return user if hmac.compare_digest(expected, sig) else None
