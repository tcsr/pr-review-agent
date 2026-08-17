from app.store.db import make_engine, make_session_factory, init_db
from app.store.tables import DeadLetter
from app.queue import Queue
from app.models import Event, Platform


def _queue(max_attempts=4):
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    return Queue(make_session_factory(engine), max_attempts=max_attempts)


def test_enqueue_and_dedup():
    q = _queue()
    first = q.enqueue("github", "o/r", 1, "abc", "code_review")
    dup = q.enqueue("github", "o/r", 1, "abc", "code_review")
    assert first is not None
    assert dup is None


def test_new_sha_not_deduped():
    q = _queue()
    q.enqueue("github", "o/r", 1, "abc", "code_review")
    other = q.enqueue("github", "o/r", 1, "def", "code_review")
    assert other is not None


def test_claim_marks_in_progress():
    q = _queue()
    q.enqueue("github", "o/r", 1, "abc", "code_review")
    job = q.claim()
    assert job.status == "in_progress"
    assert job.attempts == 1
    assert q.claim() is None  # nothing else pending


def test_enqueue_event_multi_task():
    q = _queue()
    ev = Event(platform=Platform.github, repo="o/r", pr_number=2, head_sha="s", action="opened")
    jobs = q.enqueue_event(ev, ["code_review", "summarize"])
    assert len(jobs) == 2


def test_fail_retries_then_dead_letters():
    q = _queue(max_attempts=2)
    q.enqueue("github", "o/r", 1, "abc", "code_review")
    j = q.claim()
    q.fail(j.id, "boom")           # attempts=1 < 2 -> back to pending
    j2 = q.claim()
    assert j2.attempts == 2
    q.fail(j2.id, "boom again")    # attempts=2 == max -> failed + dead letter
    assert q.claim() is None
    s = q.session_factory()
    assert s.query(DeadLetter).count() == 1


def test_complete_marks_done():
    q = _queue()
    q.enqueue("github", "o/r", 1, "abc", "code_review")
    job = q.claim()
    q.complete(job.id)
    with q.session_factory() as s:
        from app.store.tables import Job
        assert s.get(Job, job.id).status == "done"


def test_complete_missing_job_raises():
    import pytest
    q = _queue()
    with pytest.raises(ValueError):
        q.complete(9999)
