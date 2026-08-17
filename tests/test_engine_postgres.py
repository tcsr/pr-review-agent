from __future__ import annotations

from app.store.db import make_engine, _connect_args_for


def test_sqlite_url_gets_busy_timeout():
    assert _connect_args_for("sqlite:///data/agent.db") == {"timeout": 30}
    assert _connect_args_for("sqlite:///:memory:") == {"timeout": 30}


def test_postgres_url_gets_no_sqlite_args():
    assert _connect_args_for("postgresql+psycopg://user:pass@localhost/db") == {}
    assert _connect_args_for("postgresql://user:pass@localhost/db") == {}


def test_sqlite_engine_builds():
    eng = make_engine("sqlite:///:memory:")
    assert eng.dialect.name == "sqlite"
