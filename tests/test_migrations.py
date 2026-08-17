from sqlalchemy import create_engine, inspect
from app.migrate import run_migrations


def test_migration_creates_all_tables(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    run_migrations(url)
    insp = inspect(create_engine(url))
    tables = set(insp.get_table_names())
    assert {"jobs", "posted_comments", "dead_letter"} <= tables


def test_jobs_has_uq_job_constraint(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    run_migrations(url)
    insp = inspect(create_engine(url))
    names = {u["name"] for u in insp.get_unique_constraints("jobs")}
    assert "uq_job" in names


def test_migration_is_idempotent(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    run_migrations(url)
    run_migrations(url)  # second run: already at head, no error
    insp = inspect(create_engine(url))
    assert "jobs" in insp.get_table_names()
