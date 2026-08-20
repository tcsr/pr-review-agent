from app.ingress.security import verify_gitlab_token


def test_matching_token():
    assert verify_gitlab_token("s3cret", "s3cret") is True


def test_wrong_token():
    assert verify_gitlab_token("s3cret", "nope") is False


def test_missing_token():
    assert verify_gitlab_token("s3cret", None) is False
