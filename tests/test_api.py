from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.store.db import make_engine, make_session_factory, init_db
from app.queue import Queue
from app.config import Settings, LLMConfig, StoreConfig, RepoConfig, UIConfig
from app.models import Platform
from app.auth import make_session_token
from app.api import build_api_router


def _queue(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'a.db'}")
    init_db(engine)
    return Queue(make_session_factory(engine))


def _settings():
    return Settings(llm=LLMConfig(provider="fake"), store=StoreConfig(url="sqlite:///:memory:"),
                    defaults_tasks=["code_review"],
                    repos=[RepoConfig(platform=Platform.github, full_name="o/r", token="SECRET")],
                    ui=UIConfig(admin_user="admin", session_secret="sek"))


def _app(settings, queue):
    app = FastAPI()
    app.include_router(build_api_router(settings, queue))
    return app


def _authed_client(settings, queue):
    c = TestClient(_app(settings, queue))
    c.cookies.set("session", make_session_token("admin", "sek"))
    return c


def test_stats_requires_auth(tmp_path):
    c = TestClient(_app(_settings(), _queue(tmp_path)))
    assert c.get("/api/stats").status_code == 401


def test_stats_authed(tmp_path):
    s = _settings(); q = _queue(tmp_path)
    q.enqueue("github", "o/r", 1, "a", "code_review")
    r = _authed_client(s, q).get("/api/stats")
    assert r.status_code == 200
    assert r.json()["pending"] == 1


def test_repos_never_leak_token(tmp_path):
    r = _authed_client(_settings(), _queue(tmp_path)).get("/api/repos")
    assert r.status_code == 200
    body = r.text
    assert "SECRET" not in body
    assert r.json()["repos"][0]["full_name"] == "o/r"


def test_rerun_requeues(tmp_path):
    s = _settings(); q = _queue(tmp_path)
    q.enqueue("github", "o/r", 1, "a", "code_review")
    job = q.claim()
    c = _authed_client(s, q)
    r = c.post(f"/api/jobs/{job.id}/rerun")
    assert r.json() == {"requeued": True}
    assert c.post("/api/jobs/9999/rerun").status_code == 404
