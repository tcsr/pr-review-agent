from app.store.db import make_engine, make_session_factory, init_db
from app.queue import Queue
from app.config import Settings, LLMConfig, StoreConfig, RepoConfig
from app.models import Platform
from app.git.fake import FakeGitAdapter
from app.poller import poll_once
from tests.fixtures import sample_meta, sample_diff


def _queue():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    return Queue(make_session_factory(engine))


def _settings():
    return Settings(
        llm=LLMConfig(provider="fake"), store=StoreConfig(url="sqlite:///:memory:"),
        defaults_tasks=["code_review", "summarize"],
        repos=[RepoConfig(platform=Platform.github, full_name="o/r", token="t")],
    )


def test_poll_once_enqueues_jobs_for_open_prs():
    q = _queue()
    fake = FakeGitAdapter(seed={("o/r", 1): (sample_meta(head_sha="H1"), sample_diff())})
    n = poll_once(_settings(), q, adapter_for=lambda rc: fake)
    assert n == 2   # one PR x two default tasks
    job = q.claim()
    assert job.pr_number == 1


def test_poll_once_dedups_on_second_run():
    q = _queue()
    fake = FakeGitAdapter(seed={("o/r", 1): (sample_meta(head_sha="H1"), sample_diff())})
    poll_once(_settings(), q, adapter_for=lambda rc: fake)
    n2 = poll_once(_settings(), q, adapter_for=lambda rc: fake)
    assert n2 == 0   # same (repo, pr, sha, task) already queued


def test_poll_once_skips_failing_repo():
    q = _queue()
    def boom(rc):
        raise RuntimeError("api down")
    assert poll_once(_settings(), q, adapter_for=boom) == 0
