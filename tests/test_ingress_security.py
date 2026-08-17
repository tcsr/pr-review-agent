import hashlib
import hmac
from app.ingress.security import verify_github_signature


def _sig(secret, body):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_valid_signature_passes():
    body = b'{"a":1}'
    assert verify_github_signature("s3cret", body, _sig("s3cret", body)) is True


def test_wrong_secret_fails():
    body = b'{"a":1}'
    assert verify_github_signature("s3cret", body, _sig("other", body)) is False


def test_missing_header_fails():
    assert verify_github_signature("s3cret", b"{}", None) is False


def test_malformed_header_fails():
    assert verify_github_signature("s3cret", b"{}", "garbage") is False
