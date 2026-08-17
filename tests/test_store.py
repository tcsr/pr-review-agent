import pytest
from sqlalchemy.exc import IntegrityError
from app.store.db import make_engine, make_session_factory, init_db
from app.store.tables import Job


def _session():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    return make_session_factory(engine)()


def test_insert_job_defaults():
    s = _session()
    j = Job(platform="github", repo="o/r", pr_number=1, head_sha="abc", task="code_review")
    s.add(j); s.commit()
    assert j.status == "pending"
    assert j.attempts == 0
    assert j.created_at is not None


def test_dedup_unique_constraint():
    s = _session()
    args = dict(platform="github", repo="o/r", pr_number=1, head_sha="abc", task="code_review")
    s.add(Job(**args)); s.commit()
    s.add(Job(**args))
    with pytest.raises(IntegrityError):
        s.commit()
