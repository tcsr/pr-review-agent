import httpx
from app.store.db import make_engine, make_session_factory, init_db
from app.queue import Queue
from app.config import Settings, LLMConfig, StoreConfig, RepoConfig
from app.models import Platform
from app.store.tables import Job, DeadLetter
from app.worker import process_one


def _settings():
    return Settings(
        llm=LLMConfig(provider="claude", model="m", api_key="k"),
        store=StoreConfig(url="sqlite:///:memory:"),
        defaults_tasks=["summarize"],
        repos=[RepoConfig(platform=Platform.github, full_name="o/r", token="t")],
    )


def _queue():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    return Queue(make_session_factory(engine))


def _gh(request):
    p = request.url.path
    if p == "/repos/o/r/pulls/1":
        return httpx.Response(200, json={"title": "t", "body": "", "user": {"login": "a"},
                                         "base": {"sha": "b"}, "head": {"sha": "H"}, "labels": []})
    if p == "/repos/o/r/commits/H/status":
        return httpx.Response(200, json={"state": "success"})
    if p == "/repos/o/r/pulls/1/files":
        return httpx.Response(200, json=[{"filename": "a.py", "patch": "@@ +x",
                                          "additions": 1, "deletions": 0, "status": "modified"}])
    if p == "/repos/o/r/issues/1/comments":
        # GET returns list, POST returns single comment
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(201, json={"id": 1})
    return httpx.Response(404, text=p)


def _claude(request):
    return httpx.Response(200, json={"content": [{"type": "text", "text": "Summary."}],
                                     "usage": {"input_tokens": 1, "output_tokens": 1}})


def test_process_one_completes_job():
    q = _queue()
    q.enqueue("github", "o/r", 1, "H", "summarize")
    handled = process_one(q, _settings(),
                          transport_git=httpx.MockTransport(_gh),
                          transport_llm=httpx.MockTransport(_claude))
    assert handled is True
    with q.session_factory() as s:
        assert s.get(Job, 1).status == "done"


def test_process_one_no_jobs_returns_false():
    assert process_one(_queue(), _settings()) is False


def test_process_one_missing_repo_fails_job():
    q = _queue()
    q.enqueue("github", "unknown/repo", 1, "H", "summarize")
    process_one(q, _settings())
    with q.session_factory() as s:
        job = s.get(Job, 1)
    # retried back to pending (attempts<max) with error recorded
    assert job.error is not None
