from __future__ import annotations

import httpx
from app.store.db import make_engine, make_session_factory, init_db
from app.queue import Queue
from app.config import (Settings, LLMConfig, StoreConfig, RepoConfig, RulesConfig,
                        GateConfig)
from app.models import Platform
from app.store.tables import Job
from app.worker import process_one


def _queue(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'w.db'}")
    init_db(engine)
    return Queue(make_session_factory(engine))


def _settings():
    return Settings(
        llm=LLMConfig(provider="claude", model="m", api_key="k"),
        store=StoreConfig(url="sqlite:///:memory:"),
        defaults_tasks=["compliance"],
        repos=[RepoConfig(platform=Platform.github, full_name="o/r", token="t",
                          rules=RulesConfig(gates={"ci_must_pass": GateConfig(severity="block")}))],
    )


posted = {"n": 0}


def _gh(request):
    global posted
    p = request.url.path
    if p == "/repos/o/r/pulls/1":
        return httpx.Response(200, json={"title": "t", "body": "", "user": {"login": "a"},
                                         "base": {"sha": "b"}, "head": {"sha": "H"}, "labels": []})
    if p == "/repos/o/r/commits/H/status":
        return httpx.Response(200, json={"state": "failure"})
    if p == "/repos/o/r/pulls/1/files":
        return httpx.Response(200, json=[{"filename": "a.py", "patch": "@@",
                                          "additions": 1, "deletions": 0, "status": "modified"}])
    if p == "/repos/o/r/issues/1/comments":
        posted["n"] += 1
        return httpx.Response(201, json={"id": 1})
    return httpx.Response(404, text=p)


def test_worker_runs_compliance_with_repo_rules(tmp_path):
    global posted
    posted["n"] = 0
    q = _queue(tmp_path)
    q.enqueue("github", "o/r", 1, "H", "compliance")
    handled = process_one(q, _settings(), transport_git=httpx.MockTransport(_gh))
    assert handled is True
    with q.session_factory() as s:
        assert s.get(Job, 1).status == "done"
    assert posted["n"] == 1
