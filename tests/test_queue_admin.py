from __future__ import annotations

from app.store.db import make_engine, make_session_factory, init_db
from app.queue import Queue


def _queue():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    return Queue(make_session_factory(engine))


def test_stats_counts_by_status():
    q = _queue()
    q.enqueue("github", "o/r", 1, "a", "code_review")
    q.enqueue("github", "o/r", 1, "a", "summarize")
    q.claim()  # one -> in_progress
    s = q.stats()
    assert s["pending"] == 1
    assert s["in_progress"] == 1
    assert s["done"] == 0
    assert s["failed"] == 0


def test_list_jobs_newest_first():
    q = _queue()
    q.enqueue("github", "o/r", 1, "a", "code_review")
    q.enqueue("github", "o/r", 2, "b", "summarize")
    jobs = q.list_jobs()
    assert jobs[0]["pr_number"] == 2  # newest first
    assert set(jobs[0]) >= {"id", "repo", "task", "status", "attempts"}


def test_requeue_resets_job():
    q = _queue()
    q.enqueue("github", "o/r", 1, "a", "code_review")
    job = q.claim()
    q.fail(job.id, "boom")  # attempts=1
    assert q.requeue(job.id) is True
    jobs = {j["id"]: j for j in q.list_jobs()}
    assert jobs[job.id]["status"] == "pending"
    assert jobs[job.id]["attempts"] == 0
    assert jobs[job.id]["error"] is None


def test_requeue_missing_returns_false():
    assert _queue().requeue(999) is False
