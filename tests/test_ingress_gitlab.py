import json
from fastapi.testclient import TestClient
from app.store.db import make_engine, make_session_factory, init_db
from app.queue import Queue
from app.config import Settings, LLMConfig, StoreConfig, RepoConfig, IngressConfig
from app.models import Platform
from app.ingress.app import create_app


def _queue(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'g.db'}")
    init_db(engine)
    return Queue(make_session_factory(engine))


def _settings(secret="", handle="pr-agent"):
    return Settings(llm=LLMConfig(provider="fake"), store=StoreConfig(url="sqlite:///:memory:"),
                    defaults_tasks=["code_review", "summarize"],
                    repos=[RepoConfig(platform=Platform.gitlab, full_name="grp/proj", token="t")],
                    ingress=IngressConfig(webhook_secret=secret), bot_handle=handle)


def _mr_body(action="open"):
    return json.dumps({"object_kind": "merge_request",
                       "project": {"path_with_namespace": "grp/proj"},
                       "object_attributes": {"iid": 7, "action": action,
                                             "last_commit": {"id": "abc"}}}).encode()


def test_gitlab_mr_enqueues(tmp_path):
    q = _queue(tmp_path)
    client = TestClient(create_app(_settings(), q, verify=False))
    r = client.post("/webhook/gitlab", content=_mr_body(),
                    headers={"X-Gitlab-Event": "Merge Request Hook"})
    assert r.json() == {"enqueued": 2}
    assert q.claim().platform == "gitlab"


def test_gitlab_bad_token_401(tmp_path):
    q = _queue(tmp_path)
    client = TestClient(create_app(_settings(secret="sek"), q))
    r = client.post("/webhook/gitlab", content=_mr_body(),
                    headers={"X-Gitlab-Event": "Merge Request Hook",
                             "X-Gitlab-Token": "wrong"})
    assert r.status_code == 401


def test_gitlab_note_mention_enqueues_qa_reply(tmp_path):
    q = _queue(tmp_path)
    client = TestClient(create_app(_settings(), q, verify=False))
    body = json.dumps({"object_kind": "note",
                       "project": {"path_with_namespace": "grp/proj"},
                       "merge_request": {"iid": 5}, "user": {"username": "alice"},
                       "object_attributes": {"id": 3, "note": "@pr-agent why?"}}).encode()
    r = client.post("/webhook/gitlab", content=body,
                    headers={"X-Gitlab-Event": "Note Hook"})
    assert r.json() == {"enqueued": 1}
    assert q.claim().task == "qa_reply"


def test_unknown_platform_404(tmp_path):
    client = TestClient(create_app(_settings(), _queue(tmp_path), verify=False))
    r = client.post("/webhook/svn", content=b"{}", headers={})
    assert r.status_code == 404
