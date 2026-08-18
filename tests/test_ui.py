from fastapi.testclient import TestClient
from app.store.db import make_engine, make_session_factory, init_db
from app.queue import Queue
from app.config import Settings, LLMConfig, StoreConfig, RepoConfig, UIConfig
from app.models import Platform
from app.auth import hash_password
from app.ingress.app import create_app


def _queue(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'u.db'}")
    init_db(engine)
    return Queue(make_session_factory(engine))


def _settings(enabled=True):
    return Settings(llm=LLMConfig(provider="fake"), store=StoreConfig(url="sqlite:///:memory:"),
                    defaults_tasks=["code_review"],
                    repos=[RepoConfig(platform=Platform.github, full_name="o/r", token="t")],
                    ui=UIConfig(enabled=enabled, admin_user="admin",
                                admin_password_hash=hash_password("pw", salt=b"0123456789abcdef"),
                                session_secret="sek"))


def test_login_page_public(tmp_path):
    c = TestClient(create_app(_settings(), _queue(tmp_path), verify=False))
    r = c.get("/admin/login")
    assert r.status_code == 200
    assert "password" in r.text.lower()


def test_dashboard_redirects_when_unauthed(tmp_path):
    c = TestClient(create_app(_settings(), _queue(tmp_path), verify=False))
    r = c.get("/admin", follow_redirects=False)
    assert r.status_code == 303
    assert "/admin/login" in r.headers["location"]


def test_login_flow_then_dashboard(tmp_path):
    q = _queue(tmp_path)
    q.enqueue("github", "o/r", 1, "a", "code_review")
    c = TestClient(create_app(_settings(), q, verify=False))
    r = c.post("/admin/login", data={"username": "admin", "password": "pw"},
               follow_redirects=False)
    assert r.status_code == 303
    assert "session" in r.cookies
    dash = c.get("/admin")
    assert dash.status_code == 200
    assert "code_review" in dash.text  # job listed


def test_bad_login_401(tmp_path):
    c = TestClient(create_app(_settings(), _queue(tmp_path), verify=False))
    r = c.post("/admin/login", data={"username": "admin", "password": "wrong"},
               follow_redirects=False)
    assert r.status_code == 401


def test_ui_disabled_no_admin_route(tmp_path):
    c = TestClient(create_app(_settings(enabled=False), _queue(tmp_path), verify=False))
    assert c.get("/admin/login").status_code == 404
    # health still works
    assert c.get("/health").json() == {"status": "ok"}


def test_login_cookie_has_max_age(tmp_path):
    c = TestClient(create_app(_settings(), _queue(tmp_path), verify=False))
    r = c.post("/admin/login", data={"username": "admin", "password": "pw"},
               follow_redirects=False)
    set_cookie = r.headers.get("set-cookie", "")
    assert "Max-Age" in set_cookie or "max-age" in set_cookie
