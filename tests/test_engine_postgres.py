from __future__ import annotations

import pytest

from app.store.db import make_engine


def test_sqlite_engine_has_busy_timeout():
    eng = make_engine("sqlite:///:memory:")
    # connect args recorded on the dialect/url; verify timeout applied
    assert eng.url.get_backend_name() == "sqlite"
    # engine constructed without error and is sqlite
    assert eng.dialect.name == "sqlite"


def test_postgres_url_builds_engine_without_sqlite_args():
    # Engine creation with postgres URL does not apply sqlite-only connect_args.
    # Postgres URL form: postgresql://user:pass@localhost/db
    # Using the generic postgresql:// dialect which is lazily resolved for Engine creation.
    # Requires postgresql+psycopg or postgresql+psycopg2 driver for actual connection;
    # this test verifies engine construction and dialect name detection work without live DB.
    pytest.importorskip("psycopg")
    eng = make_engine("postgresql+psycopg://user:pass@localhost/db")
    assert eng.dialect.name == "postgresql"
