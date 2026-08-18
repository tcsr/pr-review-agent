from app.auth import (hash_password, verify_password, make_session_token,
                      verify_session_token)


def test_hash_verify_roundtrip():
    h = hash_password("s3cret", salt=b"0123456789abcdef")
    assert verify_password("s3cret", h) is True
    assert verify_password("wrong", h) is False


def test_hash_is_deterministic_for_fixed_salt():
    a = hash_password("pw", salt=b"0123456789abcdef")
    b = hash_password("pw", salt=b"0123456789abcdef")
    assert a == b


def test_verify_password_bad_format():
    assert verify_password("x", "not-a-valid-hash") is False


def test_session_token_roundtrip():
    tok = make_session_token("admin", "sekret")
    assert verify_session_token(tok, "sekret") == "admin"


def test_session_token_wrong_secret():
    tok = make_session_token("admin", "sekret")
    assert verify_session_token(tok, "other") is None


def test_session_token_none():
    assert verify_session_token(None, "sekret") is None
