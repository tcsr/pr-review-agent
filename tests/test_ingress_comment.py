from __future__ import annotations

import json
from fastapi.testclient import TestClient
from app.store.db import make_engine, make_session_factory, init_db
from app.queue import Queue
from app.config import Settings, LLMConfig, StoreConfig, RepoConfig
from app.models import Platform
from app.ingress.app import create_app


def _queue(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'c.db'}")
    init_db(engine)
    return Queue(make_session_factory(engine))


def _settings(handle="pr-agent"):
    return Settings(llm=LLMConfig(provider="fake"), store=StoreConfig(url="sqlite:///:memory:"),
                    defaults_tasks=["code_review", "summarize"],
                    repos=[RepoConfig(platform=Platform.github, full_name="o/r", token="t")],
                    bot_handle=handle)


def _comment_body(text="@pr-agent why?"):
    return json.dumps({"action": "created", "repository": {"full_name": "o/r"},
                       "issue": {"number": 5, "pull_request": {"url": "x"}},
                       "comment": {"id": 7, "body": text, "user": {"login": "alice"}}}).encode()


def test_comment_with_mention_enqueues_only_qa_reply(tmp_path):
    q = _queue(tmp_path)
    client = TestClient(create_app(_settings(), q, verify=False))
    r = client.post("/webhook/github", content=_comment_body(),
                    headers={"X-GitHub-Event": "issue_comment"})
    assert r.json() == {"enqueued": 1}
    job = q.claim()
    assert job.task == "qa_reply"


def test_comment_without_mention_enqueues_zero(tmp_path):
    q = _queue(tmp_path)
    client = TestClient(create_app(_settings(), q, verify=False))
    r = client.post("/webhook/github", content=_comment_body("no mention here"),
                    headers={"X-GitHub-Event": "issue_comment"})
    assert r.json() == {"enqueued": 0}


def test_comment_ignored_when_no_bot_handle(tmp_path):
    q = _queue(tmp_path)
    client = TestClient(create_app(_settings(handle=""), q, verify=False))
    r = client.post("/webhook/github", content=_comment_body(),
                    headers={"X-GitHub-Event": "issue_comment"})
    assert r.json() == {"enqueued": 0}


def test_bot_own_comment_not_enqueued(tmp_path):
    q = _queue(tmp_path)
    client = TestClient(create_app(_settings(), q, verify=False))
    body = json.dumps({"action": "created", "repository": {"full_name": "o/r"},
                       "issue": {"number": 5, "pull_request": {"url": "x"}},
                       "comment": {"id": 8, "body": "@pr-agent see above",
                                   "user": {"login": "pr-agent"}}}).encode()
    r = client.post("/webhook/github", content=body,
                    headers={"X-GitHub-Event": "issue_comment"})
    assert r.json() == {"enqueued": 0}


def test_uppercase_mention_enqueues(tmp_path):
    q = _queue(tmp_path)
    client = TestClient(create_app(_settings(), q, verify=False))
    r = client.post("/webhook/github", content=_comment_body("@PR-AGENT why?"),
                    headers={"X-GitHub-Event": "issue_comment"})
    assert r.json() == {"enqueued": 1}
