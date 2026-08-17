import hashlib
import hmac
import json
import tempfile
import os
from fastapi.testclient import TestClient
from app.store.db import make_engine, make_session_factory, init_db
from app.queue import Queue
from app.config import Settings, LLMConfig, StoreConfig, RepoConfig, IngressConfig
from app.models import Platform
from app.ingress.app import create_app


def _queue():
    # Use a unique temporary database file for each test to avoid cross-test pollution
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = make_engine(f"sqlite:///{db_path}")
    init_db(engine)
    return Queue(make_session_factory(engine))


def _settings(secret=""):
    return Settings(
        llm=LLMConfig(provider="fake"), store=StoreConfig(url="sqlite:///:memory:"),
        defaults_tasks=["code_review", "summarize"],
        repos=[RepoConfig(platform=Platform.github, full_name="o/r", token="t")],
        ingress=IngressConfig(webhook_secret=secret),
    )


def _pr_body():
    return json.dumps({"action": "opened", "repository": {"full_name": "o/r"},
                       "pull_request": {"number": 3, "head": {"sha": "z"}}}).encode()


def test_health():
    client = TestClient(create_app(_settings(), _queue()))
    assert client.get("/health").json() == {"status": "ok"}


def test_webhook_enqueues_jobs_per_task():
    q = _queue()
    client = TestClient(create_app(_settings(), q, verify=False))
    r = client.post("/webhook/github", content=_pr_body(),
                    headers={"X-GitHub-Event": "pull_request"})
    assert r.json() == {"enqueued": 2}   # code_review + summarize


def test_webhook_bad_signature_401():
    q = _queue()
    client = TestClient(create_app(_settings(secret="sekret"), q))
    r = client.post("/webhook/github", content=_pr_body(),
                    headers={"X-GitHub-Event": "pull_request",
                             "X-Hub-Signature-256": "sha256=wrong"})
    assert r.status_code == 401
    assert q.claim() is None  # nothing enqueued


def test_webhook_valid_signature_enqueues():
    q = _queue()
    body = _pr_body()
    sig = "sha256=" + hmac.new(b"sekret", body, hashlib.sha256).hexdigest()
    client = TestClient(create_app(_settings(secret="sekret"), q))
    r = client.post("/webhook/github", content=body,
                    headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": sig})
    assert r.json()["enqueued"] == 2


def test_webhook_ignored_event_enqueues_zero():
    q = _queue()
    client = TestClient(create_app(_settings(), q, verify=False))
    body = json.dumps({"action": "closed", "repository": {"full_name": "o/r"},
                       "pull_request": {"number": 3, "head": {"sha": "z"}}}).encode()
    r = client.post("/webhook/github", content=body,
                    headers={"X-GitHub-Event": "pull_request"})
    assert r.json() == {"enqueued": 0}
