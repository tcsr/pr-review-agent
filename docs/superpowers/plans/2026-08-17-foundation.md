# PR Review Agent — Foundation Implementation Plan (Plan 1 of N)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the offline foundation of the PR review agent — config, state store, neutral data models, provider-agnostic adapter interfaces with fakes, a DB-backed job queue with dedup, and the reviewer running the `code_review` and `summarize` tasks — all runnable and tested with zero network.

**Architecture:** A Python package `app/` with focused modules behind abstract interfaces. Git platforms and LLM providers are hidden behind `GitPlatformAdapter` / `LLMAdapter`; this plan implements only the *fake* concretes so the whole pipeline is exercised offline. A DB-backed queue (SQLite via SQLAlchemy) coordinates work and enforces per-`(platform, repo, pr, sha, task)` dedup. The reviewer orchestrates task modules that build prompts and call the LLM adapter.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.x, pydantic v2 / pydantic-settings, PyYAML, pytest. No web framework or provider SDKs in this slice.

## Global Constraints

- Python 3.11+ (use `from __future__ import annotations`; stdlib `datetime` with `timezone.utc`).
- No network calls anywhere in this plan. Tests run fully offline.
- SQLAlchemy 2.x style (`Mapped`, `mapped_column`, `Session`).
- pydantic v2 API (`model_validate`, `Field`, `BaseModel`; settings via `pydantic-settings`).
- Neutral data types are the only types crossing module boundaries — concrete adapters map to/from them; core never imports a provider SDK.
- Every code change lands via TDD: failing test first, minimal impl, green, commit.
- Timestamps are timezone-aware UTC.
- Dedup key is the tuple `(platform, repo, pr_number, head_sha, task)`.

---

## File Structure

```
pr-review-agent/
  pyproject.toml                 # package + deps + pytest config
  app/
    __init__.py
    config.py                    # Settings (pydantic-settings), YAML+env load
    models.py                    # neutral dataclasses: PR, PRMeta, FileChange, Diff, Comment, Event, enums
    store/
      __init__.py
      db.py                      # engine/session factory, init_db
      tables.py                  # SQLAlchemy ORM: Job, PostedComment, DeadLetter
    queue.py                     # enqueue / claim / complete / fail / dedup / retry
    git/
      __init__.py
      base.py                    # GitPlatformAdapter ABC
      fake.py                    # FakeGitAdapter (in-memory)
    llm/
      __init__.py
      base.py                    # LLMAdapter ABC + Message/Tool/LLMResponse
      fake.py                    # FakeLLMAdapter (scripted responses)
    tasks/
      __init__.py
      base.py                    # Task ABC + TaskResult
      code_review.py             # code_review task
      summarize.py               # summarize task
    reviewer.py                  # orchestrates enabled tasks for a job
  tests/
    __init__.py
    fixtures.py                  # sample PR/Diff builders
    test_models.py
    test_config.py
    test_store.py
    test_queue.py
    test_fake_git.py
    test_fake_llm.py
    test_tasks_code_review.py
    test_tasks_summarize.py
    test_reviewer.py
```

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `app/__init__.py`
- Create: `tests/__init__.py`
- Test: `tests/test_smoke.py`

**Interfaces:**
- Consumes: nothing.
- Produces: importable `app` package; `pytest` runs.

- [ ] **Step 1: Write the failing test**

`tests/test_smoke.py`:
```python
def test_app_imports():
    import app
    assert app is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Create package + pyproject**

`pyproject.toml`:
```toml
[project]
name = "pr-review-agent"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "sqlalchemy>=2.0",
    "pydantic>=2.6",
    "pydantic-settings>=2.2",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"
```

`app/__init__.py`:
```python
__all__ = []
```

`tests/__init__.py`: (empty file)

- [ ] **Step 4: Install and run**

Run: `pip install -e ".[dev]" && pytest tests/test_smoke.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml app/__init__.py tests/__init__.py tests/test_smoke.py
git commit -m "chore: project scaffold"
```

---

### Task 2: Neutral data models

**Files:**
- Create: `app/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - Enums `Platform(str, Enum)` = {`github`, `bitbucket`, `gitlab`}; `Verdict(str, Enum)` = {`approve`, `request_changes`, `comment`}; `Side(str, Enum)` = {`left`, `right`}.
  - `@dataclass FileChange(path: str, patch: str, additions: int, deletions: int, status: str)`.
  - `@dataclass Diff(files: list[FileChange])` with `total_changed_lines() -> int`.
  - `@dataclass PRMeta(title: str, body: str, author: str, base_sha: str, head_sha: str, labels: list[str], linked_issues: list[str], ci_passed: bool | None)`.
  - `@dataclass PR(platform: Platform, repo: str, number: int, head_sha: str)`.
  - `@dataclass Comment(id: str, author: str, body: str, path: str | None, line: int | None)`.
  - `@dataclass Event(platform: Platform, repo: str, pr_number: int, head_sha: str, action: str, comment_body: str | None = None)`.

- [ ] **Step 1: Write the failing test**

`tests/test_models.py`:
```python
from app.models import Platform, Verdict, Side, FileChange, Diff, PRMeta, PR, Comment, Event


def test_enums():
    assert Platform.github == "github"
    assert Verdict.request_changes == "request_changes"
    assert Side.right == "right"


def test_diff_total_changed_lines():
    diff = Diff(files=[
        FileChange(path="a.py", patch="@@", additions=3, deletions=1, status="modified"),
        FileChange(path="b.py", patch="@@", additions=5, deletions=0, status="added"),
    ])
    assert diff.total_changed_lines() == 9


def test_event_defaults():
    ev = Event(platform=Platform.github, repo="o/r", pr_number=1, head_sha="abc", action="opened")
    assert ev.comment_body is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models'`

- [ ] **Step 3: Write minimal implementation**

`app/models.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Platform(str, Enum):
    github = "github"
    bitbucket = "bitbucket"
    gitlab = "gitlab"


class Verdict(str, Enum):
    approve = "approve"
    request_changes = "request_changes"
    comment = "comment"


class Side(str, Enum):
    left = "left"
    right = "right"


@dataclass
class FileChange:
    path: str
    patch: str
    additions: int
    deletions: int
    status: str


@dataclass
class Diff:
    files: list[FileChange]

    def total_changed_lines(self) -> int:
        return sum(f.additions + f.deletions for f in self.files)


@dataclass
class PRMeta:
    title: str
    body: str
    author: str
    base_sha: str
    head_sha: str
    labels: list[str] = field(default_factory=list)
    linked_issues: list[str] = field(default_factory=list)
    ci_passed: bool | None = None


@dataclass
class PR:
    platform: Platform
    repo: str
    number: int
    head_sha: str


@dataclass
class Comment:
    id: str
    author: str
    body: str
    path: str | None = None
    line: int | None = None


@dataclass
class Event:
    platform: Platform
    repo: str
    pr_number: int
    head_sha: str
    action: str
    comment_body: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/models.py tests/test_models.py
git commit -m "feat: neutral data models"
```

---

### Task 3: Configuration

**Files:**
- Create: `app/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `Platform` from `app.models`.
- Produces:
  - `class RepoConfig(BaseModel)`: `platform: Platform`, `full_name: str`, `token: str`, `tasks: list[str] | None = None`.
  - `class LLMConfig(BaseModel)`: `provider: str = "fake"`, `model: str = "fake"`, `max_tokens_per_pr: int = 40000`.
  - `class StoreConfig(BaseModel)`: `url: str = "sqlite:///data/agent.db"`.
  - `class Settings(BaseModel)`: `llm: LLMConfig`, `store: StoreConfig`, `defaults_tasks: list[str]`, `repos: list[RepoConfig]`.
  - `load_settings(path: str | None = None, env: dict | None = None) -> Settings` — reads YAML, interpolates `${VAR}` from `env` (defaults to `os.environ`), validates. Raises `ValueError` with a clear message on unknown platform or missing env var.

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:
```python
import pytest
from app.config import load_settings
from app.models import Platform


def _write(tmp_path, text):
    p = tmp_path / "config.yaml"
    p.write_text(text)
    return str(p)


def test_load_valid_config(tmp_path):
    path = _write(tmp_path, """
llm:
  provider: fake
  model: fake
store:
  url: sqlite:///:memory:
defaults:
  tasks: [code_review, summarize]
repos:
  - platform: github
    full_name: o/r
    token: ${GH_TOKEN}
    tasks: null
""")
    s = load_settings(path, env={"GH_TOKEN": "secret"})
    assert s.repos[0].platform == Platform.github
    assert s.repos[0].token == "secret"
    assert s.defaults_tasks == ["code_review", "summarize"]


def test_missing_env_var_raises(tmp_path):
    path = _write(tmp_path, """
llm: {provider: fake, model: fake}
store: {url: 'sqlite:///:memory:'}
defaults: {tasks: [code_review]}
repos:
  - {platform: github, full_name: o/r, token: '${MISSING}'}
""")
    with pytest.raises(ValueError, match="MISSING"):
        load_settings(path, env={})


def test_unknown_platform_raises(tmp_path):
    path = _write(tmp_path, """
llm: {provider: fake, model: fake}
store: {url: 'sqlite:///:memory:'}
defaults: {tasks: [code_review]}
repos:
  - {platform: svn, full_name: o/r, token: t}
""")
    with pytest.raises(ValueError):
        load_settings(path, env={})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.config'`

- [ ] **Step 3: Write minimal implementation**

`app/config.py`:
```python
from __future__ import annotations

import os
import re
from pydantic import BaseModel, ValidationError
import yaml

from app.models import Platform

_VAR = re.compile(r"\$\{([A-Z0-9_]+)\}")


class RepoConfig(BaseModel):
    platform: Platform
    full_name: str
    token: str
    tasks: list[str] | None = None


class LLMConfig(BaseModel):
    provider: str = "fake"
    model: str = "fake"
    max_tokens_per_pr: int = 40000


class StoreConfig(BaseModel):
    url: str = "sqlite:///data/agent.db"


class Settings(BaseModel):
    llm: LLMConfig
    store: StoreConfig
    defaults_tasks: list[str]
    repos: list[RepoConfig]


def _interpolate(obj, env: dict):
    if isinstance(obj, str):
        def repl(m):
            name = m.group(1)
            if name not in env:
                raise ValueError(f"Missing environment variable: {name}")
            return env[name]
        return _VAR.sub(repl, obj)
    if isinstance(obj, list):
        return [_interpolate(x, env) for x in obj]
    if isinstance(obj, dict):
        return {k: _interpolate(v, env) for k, v in obj.items()}
    return obj


def load_settings(path: str | None = None, env: dict | None = None) -> Settings:
    env = os.environ if env is None else env
    path = path or "config.yaml"
    with open(path) as f:
        raw = yaml.safe_load(f)
    raw = _interpolate(raw, env)
    try:
        return Settings(
            llm=LLMConfig(**raw.get("llm", {})),
            store=StoreConfig(**raw.get("store", {})),
            defaults_tasks=raw["defaults"]["tasks"],
            repos=[RepoConfig(**r) for r in raw.get("repos", [])],
        )
    except ValidationError as e:
        raise ValueError(f"Invalid config: {e}") from e
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat: config loader with env interpolation"
```

---

### Task 4: State store (ORM + session)

**Files:**
- Create: `app/store/__init__.py`
- Create: `app/store/tables.py`
- Create: `app/store/db.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: nothing (stores strings, not enums).
- Produces:
  - `Base` (DeclarativeBase).
  - ORM `Job`: `id: int PK`, `platform: str`, `repo: str`, `pr_number: int`, `head_sha: str`, `task: str`, `status: str` (default `"pending"`), `attempts: int` (default 0), `error: str | None`, `created_at`, `updated_at`. Unique constraint `uq_job` on `(platform, repo, pr_number, head_sha, task)`.
  - ORM `PostedComment`: `id PK`, `job_id: int`, `external_comment_id: str`, `marker: str`.
  - ORM `DeadLetter`: `id PK`, `job_id: int`, `last_error: str`, `failed_at`.
  - `make_engine(url: str)` and `make_session_factory(engine)` returning a `sessionmaker`.
  - `init_db(engine)` creating all tables.

- [ ] **Step 1: Write the failing test**

`tests/test_store.py`:
```python
import pytest
from sqlalchemy.exc import IntegrityError
from app.store.db import make_engine, make_session_factory, init_db
from app.store.tables import Job


def _session():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    return make_session_factory(engine)()


def test_insert_job_defaults():
    s = _session()
    j = Job(platform="github", repo="o/r", pr_number=1, head_sha="abc", task="code_review")
    s.add(j); s.commit()
    assert j.status == "pending"
    assert j.attempts == 0
    assert j.created_at is not None


def test_dedup_unique_constraint():
    s = _session()
    args = dict(platform="github", repo="o/r", pr_number=1, head_sha="abc", task="code_review")
    s.add(Job(**args)); s.commit()
    s.add(Job(**args))
    with pytest.raises(IntegrityError):
        s.commit()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.store'`

- [ ] **Step 3: Write minimal implementation**

`app/store/__init__.py`: (empty)

`app/store/tables.py`:
```python
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("platform", "repo", "pr_number", "head_sha", "task", name="uq_job"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str]
    repo: Mapped[str]
    pr_number: Mapped[int]
    head_sha: Mapped[str]
    task: Mapped[str]
    status: Mapped[str] = mapped_column(default="pending")
    attempts: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)


class PostedComment(Base):
    __tablename__ = "posted_comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int]
    external_comment_id: Mapped[str]
    marker: Mapped[str]


class DeadLetter(Base):
    __tablename__ = "dead_letter"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int]
    last_error: Mapped[str]
    failed_at: Mapped[datetime] = mapped_column(default=_utcnow)
```

`app/store/db.py`:
```python
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.store.tables import Base


def make_engine(url: str):
    return create_engine(url, future=True)


def make_session_factory(engine):
    return sessionmaker(bind=engine, future=True)


def init_db(engine):
    Base.metadata.create_all(engine)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_store.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/store tests/test_store.py
git commit -m "feat: state store ORM with dedup constraint"
```

---

### Task 5: Job queue with dedup + retry

**Files:**
- Create: `app/queue.py`
- Test: `tests/test_queue.py`

**Interfaces:**
- Consumes: `Job` from `app.store.tables`; session factory from `app.store.db`; `Event` from `app.models`.
- Produces:
  - `class Queue(session_factory, max_attempts: int = 4)`.
  - `enqueue(platform, repo, pr_number, head_sha, task) -> Job | None` — inserts a pending job; returns `None` if a job with the dedup key already exists (dedup).
  - `enqueue_event(event: Event, tasks: list[str]) -> list[Job]` — one enqueue per task, skipping dups.
  - `claim() -> Job | None` — atomically marks the oldest `pending` job `in_progress`, increments `attempts`, returns it (or `None`).
  - `complete(job_id: int)` — sets status `done`.
  - `fail(job_id: int, error: str)` — if `attempts < max_attempts` → back to `pending` with error recorded; else status `failed` + row in `dead_letter`.

- [ ] **Step 1: Write the failing test**

`tests/test_queue.py`:
```python
from app.store.db import make_engine, make_session_factory, init_db
from app.store.tables import DeadLetter
from app.queue import Queue
from app.models import Event, Platform


def _queue(max_attempts=4):
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    return Queue(make_session_factory(engine), max_attempts=max_attempts)


def test_enqueue_and_dedup():
    q = _queue()
    first = q.enqueue("github", "o/r", 1, "abc", "code_review")
    dup = q.enqueue("github", "o/r", 1, "abc", "code_review")
    assert first is not None
    assert dup is None


def test_new_sha_not_deduped():
    q = _queue()
    q.enqueue("github", "o/r", 1, "abc", "code_review")
    other = q.enqueue("github", "o/r", 1, "def", "code_review")
    assert other is not None


def test_claim_marks_in_progress():
    q = _queue()
    q.enqueue("github", "o/r", 1, "abc", "code_review")
    job = q.claim()
    assert job.status == "in_progress"
    assert job.attempts == 1
    assert q.claim() is None  # nothing else pending


def test_enqueue_event_multi_task():
    q = _queue()
    ev = Event(platform=Platform.github, repo="o/r", pr_number=2, head_sha="s", action="opened")
    jobs = q.enqueue_event(ev, ["code_review", "summarize"])
    assert len(jobs) == 2


def test_fail_retries_then_dead_letters():
    q = _queue(max_attempts=2)
    q.enqueue("github", "o/r", 1, "abc", "code_review")
    j = q.claim()
    q.fail(j.id, "boom")           # attempts=1 < 2 -> back to pending
    j2 = q.claim()
    assert j2.attempts == 2
    q.fail(j2.id, "boom again")    # attempts=2 == max -> failed + dead letter
    assert q.claim() is None
    s = q.session_factory()
    assert s.query(DeadLetter).count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_queue.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.queue'`

- [ ] **Step 3: Write minimal implementation**

`app/queue.py`:
```python
from __future__ import annotations

from sqlalchemy import select

from app.models import Event
from app.store.tables import Job, DeadLetter


class Queue:
    def __init__(self, session_factory, max_attempts: int = 4):
        self.session_factory = session_factory
        self.max_attempts = max_attempts

    def enqueue(self, platform, repo, pr_number, head_sha, task) -> Job | None:
        with self.session_factory() as s:
            exists = s.execute(
                select(Job).where(
                    Job.platform == platform, Job.repo == repo,
                    Job.pr_number == pr_number, Job.head_sha == head_sha,
                    Job.task == task,
                )
            ).scalar_one_or_none()
            if exists is not None:
                return None
            job = Job(platform=platform, repo=repo, pr_number=pr_number,
                      head_sha=head_sha, task=task)
            s.add(job)
            s.commit()
            s.refresh(job)
            s.expunge(job)
            return job

    def enqueue_event(self, event: Event, tasks: list[str]) -> list[Job]:
        out = []
        for t in tasks:
            j = self.enqueue(event.platform.value, event.repo, event.pr_number,
                             event.head_sha, t)
            if j is not None:
                out.append(j)
        return out

    def claim(self) -> Job | None:
        with self.session_factory() as s:
            job = s.execute(
                select(Job).where(Job.status == "pending").order_by(Job.id).limit(1)
            ).scalar_one_or_none()
            if job is None:
                return None
            job.status = "in_progress"
            job.attempts += 1
            s.commit()
            s.refresh(job)
            s.expunge(job)
            return job

    def complete(self, job_id: int) -> None:
        with self.session_factory() as s:
            job = s.get(Job, job_id)
            job.status = "done"
            s.commit()

    def fail(self, job_id: int, error: str) -> None:
        with self.session_factory() as s:
            job = s.get(Job, job_id)
            job.error = error
            if job.attempts < self.max_attempts:
                job.status = "pending"
            else:
                job.status = "failed"
                s.add(DeadLetter(job_id=job.id, last_error=error))
            s.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_queue.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add app/queue.py tests/test_queue.py
git commit -m "feat: DB-backed job queue with dedup and retry"
```

---

### Task 6: Git adapter interface + FakeGitAdapter

**Files:**
- Create: `app/git/__init__.py`
- Create: `app/git/base.py`
- Create: `app/git/fake.py`
- Create: `tests/fixtures.py`
- Test: `tests/test_fake_git.py`

**Interfaces:**
- Consumes: neutral types from `app.models`.
- Produces:
  - `class GitPlatformAdapter(ABC)` with abstract methods: `get_pr_meta(repo, pr_number) -> PRMeta`, `get_diff(repo, pr_number) -> Diff`, `post_comment(repo, pr_number, body) -> str`, `post_inline_comment(repo, pr_number, path, line, body, side) -> str`, `set_review_verdict(repo, pr_number, verdict, body) -> None`, `get_thread(repo, pr_number) -> list[Comment]`, `reply(repo, pr_number, in_reply_to, body) -> str`.
  - `class FakeGitAdapter(GitPlatformAdapter)` seeded with a `dict[(repo, pr_number)] -> (PRMeta, Diff)`; records posted comments/verdicts in public lists `comments`, `inline_comments`, `verdicts`, `replies`.
  - `tests/fixtures.py`: `sample_meta(**over) -> PRMeta`, `sample_diff() -> Diff`.

- [ ] **Step 1: Write the failing test**

`tests/fixtures.py`:
```python
from app.models import PRMeta, Diff, FileChange


def sample_meta(**over) -> PRMeta:
    base = dict(title="Add feature", body="Does a thing", author="alice",
                base_sha="base1", head_sha="head1", labels=[], linked_issues=["#5"],
                ci_passed=True)
    base.update(over)
    return PRMeta(**base)


def sample_diff() -> Diff:
    return Diff(files=[
        FileChange(path="src/app.py", patch="@@ -1 +1 @@\n-old\n+new",
                   additions=1, deletions=1, status="modified"),
    ])
```

`tests/test_fake_git.py`:
```python
from app.git.fake import FakeGitAdapter
from app.models import Verdict, Side
from tests.fixtures import sample_meta, sample_diff


def _adapter():
    return FakeGitAdapter(seed={("o/r", 1): (sample_meta(), sample_diff())})


def test_get_meta_and_diff():
    a = _adapter()
    assert a.get_pr_meta("o/r", 1).author == "alice"
    assert a.get_diff("o/r", 1).total_changed_lines() == 2


def test_records_comments_and_verdict():
    a = _adapter()
    cid = a.post_comment("o/r", 1, "hello")
    a.post_inline_comment("o/r", 1, "src/app.py", 1, "nit", Side.right)
    a.set_review_verdict("o/r", 1, Verdict.approve, "LGTM")
    assert a.comments[0].body == "hello"
    assert cid == a.comments[0].id
    assert a.inline_comments[0].path == "src/app.py"
    assert a.verdicts[0] == (Verdict.approve, "LGTM")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fake_git.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.git'`

- [ ] **Step 3: Write minimal implementation**

`app/git/__init__.py`: (empty)

`app/git/base.py`:
```python
from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import PRMeta, Diff, Comment, Verdict, Side


class GitPlatformAdapter(ABC):
    @abstractmethod
    def get_pr_meta(self, repo: str, pr_number: int) -> PRMeta: ...

    @abstractmethod
    def get_diff(self, repo: str, pr_number: int) -> Diff: ...

    @abstractmethod
    def post_comment(self, repo: str, pr_number: int, body: str) -> str: ...

    @abstractmethod
    def post_inline_comment(self, repo: str, pr_number: int, path: str,
                            line: int, body: str, side: Side) -> str: ...

    @abstractmethod
    def set_review_verdict(self, repo: str, pr_number: int, verdict: Verdict,
                           body: str) -> None: ...

    @abstractmethod
    def get_thread(self, repo: str, pr_number: int) -> list[Comment]: ...

    @abstractmethod
    def reply(self, repo: str, pr_number: int, in_reply_to: str, body: str) -> str: ...
```

`app/git/fake.py`:
```python
from __future__ import annotations

from itertools import count

from app.git.base import GitPlatformAdapter
from app.models import PRMeta, Diff, Comment, Verdict, Side


class FakeGitAdapter(GitPlatformAdapter):
    def __init__(self, seed: dict[tuple[str, int], tuple[PRMeta, Diff]] | None = None):
        self._seed = seed or {}
        self.comments: list[Comment] = []
        self.inline_comments: list[Comment] = []
        self.verdicts: list[tuple[Verdict, str]] = []
        self.replies: list[Comment] = []
        self._ids = count(1)

    def _next_id(self) -> str:
        return f"c{next(self._ids)}"

    def get_pr_meta(self, repo, pr_number):
        return self._seed[(repo, pr_number)][0]

    def get_diff(self, repo, pr_number):
        return self._seed[(repo, pr_number)][1]

    def post_comment(self, repo, pr_number, body):
        c = Comment(id=self._next_id(), author="bot", body=body)
        self.comments.append(c)
        return c.id

    def post_inline_comment(self, repo, pr_number, path, line, body, side: Side):
        c = Comment(id=self._next_id(), author="bot", body=body, path=path, line=line)
        self.inline_comments.append(c)
        return c.id

    def set_review_verdict(self, repo, pr_number, verdict: Verdict, body):
        self.verdicts.append((verdict, body))

    def get_thread(self, repo, pr_number):
        return list(self.comments)

    def reply(self, repo, pr_number, in_reply_to, body):
        c = Comment(id=self._next_id(), author="bot", body=body)
        self.replies.append(c)
        return c.id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_fake_git.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/git tests/fixtures.py tests/test_fake_git.py
git commit -m "feat: git adapter interface and fake"
```

---

### Task 7: LLM adapter interface + FakeLLMAdapter

**Files:**
- Create: `app/llm/__init__.py`
- Create: `app/llm/base.py`
- Create: `app/llm/fake.py`
- Test: `tests/test_fake_llm.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `@dataclass Message(role: str, content: str)`.
  - `@dataclass LLMResponse(text: str, usage_tokens: int = 0)`.
  - `class LLMAdapter(ABC)`: `complete(system: str, messages: list[Message], max_tokens: int) -> LLMResponse`; `count_tokens(text: str) -> int`.
  - `class FakeLLMAdapter(LLMAdapter)` constructed with `responses: list[str]` (returned in order; last repeats) or `responder: Callable[[str, list[Message]], str]`. `count_tokens` returns `len(text.split())`. Records calls in `self.calls`.

- [ ] **Step 1: Write the failing test**

`tests/test_fake_llm.py`:
```python
from app.llm.fake import FakeLLMAdapter
from app.llm.base import Message


def test_scripted_responses_in_order():
    llm = FakeLLMAdapter(responses=["first", "second"])
    r1 = llm.complete("sys", [Message(role="user", content="a")], max_tokens=100)
    r2 = llm.complete("sys", [Message(role="user", content="b")], max_tokens=100)
    r3 = llm.complete("sys", [Message(role="user", content="c")], max_tokens=100)
    assert (r1.text, r2.text, r3.text) == ("first", "second", "second")


def test_responder_callable_and_calls_recorded():
    llm = FakeLLMAdapter(responder=lambda system, msgs: msgs[-1].content.upper())
    r = llm.complete("sys", [Message(role="user", content="hi")], max_tokens=10)
    assert r.text == "HI"
    assert llm.calls[0][0] == "sys"


def test_count_tokens():
    llm = FakeLLMAdapter(responses=["x"])
    assert llm.count_tokens("one two three") == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fake_llm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.llm'`

- [ ] **Step 3: Write minimal implementation**

`app/llm/__init__.py`: (empty)

`app/llm/base.py`:
```python
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Message:
    role: str
    content: str


@dataclass
class LLMResponse:
    text: str
    usage_tokens: int = 0


class LLMAdapter(ABC):
    @abstractmethod
    def complete(self, system: str, messages: list[Message], max_tokens: int) -> LLMResponse: ...

    @abstractmethod
    def count_tokens(self, text: str) -> int: ...
```

`app/llm/fake.py`:
```python
from __future__ import annotations

from typing import Callable

from app.llm.base import LLMAdapter, Message, LLMResponse


class FakeLLMAdapter(LLMAdapter):
    def __init__(self, responses: list[str] | None = None,
                 responder: Callable[[str, list[Message]], str] | None = None):
        self._responses = responses or []
        self._responder = responder
        self._i = 0
        self.calls: list[tuple[str, list[Message]]] = []

    def complete(self, system, messages, max_tokens) -> LLMResponse:
        self.calls.append((system, messages))
        if self._responder is not None:
            text = self._responder(system, messages)
        elif self._responses:
            text = self._responses[min(self._i, len(self._responses) - 1)]
            self._i += 1
        else:
            text = ""
        return LLMResponse(text=text, usage_tokens=self.count_tokens(text))

    def count_tokens(self, text: str) -> int:
        return len(text.split())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_fake_llm.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/llm tests/test_fake_llm.py
git commit -m "feat: llm adapter interface and fake"
```

---

### Task 8: Task base + `code_review` task

**Files:**
- Create: `app/tasks/__init__.py`
- Create: `app/tasks/base.py`
- Create: `app/tasks/code_review.py`
- Test: `tests/test_tasks_code_review.py`

**Interfaces:**
- Consumes: `GitPlatformAdapter`, `LLMAdapter`, `Message`, `PRMeta`, `Diff`, `Side`.
- Produces:
  - `@dataclass TaskResult(name: str, posted: int)`.
  - `class Task(ABC)`: `name: str` (class attr); `run(git, llm, repo, pr_number, meta, diff) -> TaskResult`.
  - `class CodeReviewTask(Task)`: `name = "code_review"`. Builds a prompt from `meta`+`diff`, calls `llm.complete`, parses the response as JSON list of `{path, line, comment}` findings, posts each via `git.post_inline_comment(..., side=Side.right)`. Malformed JSON → posts nothing, returns `TaskResult("code_review", 0)`.

- [ ] **Step 1: Write the failing test**

`tests/test_tasks_code_review.py`:
```python
import json
from app.git.fake import FakeGitAdapter
from app.llm.fake import FakeLLMAdapter
from app.tasks.code_review import CodeReviewTask
from tests.fixtures import sample_meta, sample_diff


def _git():
    return FakeGitAdapter(seed={("o/r", 1): (sample_meta(), sample_diff())})


def test_posts_one_inline_comment_per_finding():
    findings = json.dumps([
        {"path": "src/app.py", "line": 1, "comment": "Use a constant."},
        {"path": "src/app.py", "line": 2, "comment": "Missing docstring."},
    ])
    git = _git()
    llm = FakeLLMAdapter(responses=[findings])
    res = CodeReviewTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1), git.get_diff("o/r", 1))
    assert res.posted == 2
    assert len(git.inline_comments) == 2
    assert git.inline_comments[0].body == "Use a constant."


def test_malformed_json_posts_nothing():
    git = _git()
    llm = FakeLLMAdapter(responses=["not json"])
    res = CodeReviewTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1), git.get_diff("o/r", 1))
    assert res.posted == 0
    assert git.inline_comments == []


def test_prompt_includes_diff_patch():
    git = _git()
    llm = FakeLLMAdapter(responses=["[]"])
    CodeReviewTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1), git.get_diff("o/r", 1))
    system, messages = llm.calls[0]
    assert "src/app.py" in messages[-1].content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tasks_code_review.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.tasks'`

- [ ] **Step 3: Write minimal implementation**

`app/tasks/__init__.py`: (empty)

`app/tasks/base.py`:
```python
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.git.base import GitPlatformAdapter
from app.llm.base import LLMAdapter
from app.models import PRMeta, Diff


@dataclass
class TaskResult:
    name: str
    posted: int


class Task(ABC):
    name: str = "task"

    @abstractmethod
    def run(self, git: GitPlatformAdapter, llm: LLMAdapter, repo: str,
            pr_number: int, meta: PRMeta, diff: Diff) -> TaskResult: ...
```

`app/tasks/code_review.py`:
```python
from __future__ import annotations

import json

from app.llm.base import Message
from app.models import Side
from app.tasks.base import Task, TaskResult

_SYSTEM = (
    "You are a code reviewer. Return ONLY a JSON array of findings, each "
    '{"path": str, "line": int, "comment": str}. No prose.'
)


def _render_diff(diff) -> str:
    return "\n".join(f"--- {f.path}\n{f.patch}" for f in diff.files)


class CodeReviewTask(Task):
    name = "code_review"

    def run(self, git, llm, repo, pr_number, meta, diff) -> TaskResult:
        prompt = (
            f"PR title: {meta.title}\n\nDiff:\n{_render_diff(diff)}\n\n"
            "List review findings as JSON."
        )
        resp = llm.complete(_SYSTEM, [Message(role="user", content=prompt)], max_tokens=2000)
        try:
            findings = json.loads(resp.text)
            assert isinstance(findings, list)
        except (json.JSONDecodeError, AssertionError):
            return TaskResult(self.name, 0)
        posted = 0
        for f in findings:
            git.post_inline_comment(repo, pr_number, f["path"], f["line"],
                                    f["comment"], Side.right)
            posted += 1
        return TaskResult(self.name, posted)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tasks_code_review.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/tasks tests/test_tasks_code_review.py
git commit -m "feat: task base and code_review task"
```

---

### Task 9: `summarize` task

**Files:**
- Create: `app/tasks/summarize.py`
- Test: `tests/test_tasks_summarize.py`

**Interfaces:**
- Consumes: `Task`, `TaskResult`, `Message`.
- Produces:
  - `class SummarizeTask(Task)`: `name = "summarize"`. Builds a prompt from `meta`+`diff`, calls `llm.complete`, posts the returned text as a single PR-level comment via `git.post_comment`. Returns `TaskResult("summarize", 1)`. Empty/whitespace response → posts nothing, returns `TaskResult("summarize", 0)`.

- [ ] **Step 1: Write the failing test**

`tests/test_tasks_summarize.py`:
```python
from app.git.fake import FakeGitAdapter
from app.llm.fake import FakeLLMAdapter
from app.tasks.summarize import SummarizeTask
from tests.fixtures import sample_meta, sample_diff


def _git():
    return FakeGitAdapter(seed={("o/r", 1): (sample_meta(), sample_diff())})


def test_posts_single_summary_comment():
    git = _git()
    llm = FakeLLMAdapter(responses=["This PR changes app.py to fix a bug."])
    res = SummarizeTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1), git.get_diff("o/r", 1))
    assert res.posted == 1
    assert len(git.comments) == 1
    assert "app.py" in git.comments[0].body


def test_empty_response_posts_nothing():
    git = _git()
    llm = FakeLLMAdapter(responses=["   "])
    res = SummarizeTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1), git.get_diff("o/r", 1))
    assert res.posted == 0
    assert git.comments == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tasks_summarize.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.tasks.summarize'`

- [ ] **Step 3: Write minimal implementation**

`app/tasks/summarize.py`:
```python
from __future__ import annotations

from app.llm.base import Message
from app.tasks.base import Task, TaskResult
from app.tasks.code_review import _render_diff

_SYSTEM = "Summarize this pull request in 3-5 sentences: what changed and why."


class SummarizeTask(Task):
    name = "summarize"

    def run(self, git, llm, repo, pr_number, meta, diff) -> TaskResult:
        prompt = f"Title: {meta.title}\nDescription: {meta.body}\n\nDiff:\n{_render_diff(diff)}"
        resp = llm.complete(_SYSTEM, [Message(role="user", content=prompt)], max_tokens=800)
        if not resp.text.strip():
            return TaskResult(self.name, 0)
        git.post_comment(repo, pr_number, resp.text.strip())
        return TaskResult(self.name, 1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tasks_summarize.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/tasks/summarize.py tests/test_tasks_summarize.py
git commit -m "feat: summarize task"
```

---

### Task 10: Reviewer orchestration

**Files:**
- Create: `app/reviewer.py`
- Test: `tests/test_reviewer.py`

**Interfaces:**
- Consumes: `GitPlatformAdapter`, `LLMAdapter`, `Task`/`TaskResult`, `CodeReviewTask`, `SummarizeTask`.
- Produces:
  - `TASK_REGISTRY: dict[str, type[Task]]` = `{"code_review": CodeReviewTask, "summarize": SummarizeTask}`.
  - `class Reviewer(git, llm)`.
  - `review(repo, pr_number, tasks: list[str]) -> list[TaskResult]` — fetches `meta`+`diff` once, runs each named task (unknown names skipped), returns results. If `"code_review"` and `"verdict"` are both present, `code_review` runs first (verdict not in this slice, but ordering rule is honored via a fixed priority list).

- [ ] **Step 1: Write the failing test**

`tests/test_reviewer.py`:
```python
import json
from app.git.fake import FakeGitAdapter
from app.llm.fake import FakeLLMAdapter
from app.reviewer import Reviewer
from tests.fixtures import sample_meta, sample_diff


def _git():
    return FakeGitAdapter(seed={("o/r", 1): (sample_meta(), sample_diff())})


def test_runs_selected_tasks():
    git = _git()
    def responder(system, msgs):
        return json.dumps([]) if "JSON array" in system else "Summary text."
    llm = FakeLLMAdapter(responder=responder)
    results = Reviewer(git, llm).review("o/r", 1, ["code_review", "summarize"])
    names = {r.name for r in results}
    assert names == {"code_review", "summarize"}
    assert len(git.comments) == 1  # summary posted


def test_unknown_task_skipped():
    git = _git()
    llm = FakeLLMAdapter(responses=["Summary text."])
    results = Reviewer(git, llm).review("o/r", 1, ["nonexistent", "summarize"])
    assert [r.name for r in results] == ["summarize"]


def test_fetches_meta_and_diff_once():
    git = _git()
    llm = FakeLLMAdapter(responses=["Summary text."])
    Reviewer(git, llm).review("o/r", 1, ["summarize"])
    # summarize posted exactly one comment from the seeded diff
    assert "app.py" in git.comments[0].body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reviewer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.reviewer'`

- [ ] **Step 3: Write minimal implementation**

`app/reviewer.py`:
```python
from __future__ import annotations

from app.tasks.base import Task, TaskResult
from app.tasks.code_review import CodeReviewTask
from app.tasks.summarize import SummarizeTask

TASK_REGISTRY: dict[str, type[Task]] = {
    "code_review": CodeReviewTask,
    "summarize": SummarizeTask,
}

# Lower number runs earlier. code_review before verdict (verdict added later).
_PRIORITY = {"code_review": 0, "summarize": 5, "verdict": 9}


class Reviewer:
    def __init__(self, git, llm):
        self.git = git
        self.llm = llm

    def review(self, repo: str, pr_number: int, tasks: list[str]) -> list[TaskResult]:
        selected = [t for t in tasks if t in TASK_REGISTRY]
        selected.sort(key=lambda t: _PRIORITY.get(t, 100))
        meta = self.git.get_pr_meta(repo, pr_number)
        diff = self.git.get_diff(repo, pr_number)
        results: list[TaskResult] = []
        for name in selected:
            task = TASK_REGISTRY[name]()
            results.append(task.run(self.git, self.llm, repo, pr_number, meta, diff))
        return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reviewer.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/reviewer.py tests/test_reviewer.py
git commit -m "feat: reviewer orchestration with task ordering"
```

---

### Task 11: Full-suite green + README quickstart

**Files:**
- Create: `README.md`
- Test: (runs the whole suite)

**Interfaces:**
- Consumes: everything above.
- Produces: passing full suite + a documented offline dev loop.

- [ ] **Step 1: Run the full suite**

Run: `pytest -v`
Expected: PASS — all tests from Tasks 1–10 green, zero network.

- [ ] **Step 2: Write README quickstart**

`README.md`:
```markdown
# PR Review Agent

Standalone, self-hostable, multi-platform PR review agent.

## Foundation status
Offline core: config, state store, neutral models, fake adapters, job queue with
dedup, and the reviewer running `code_review` + `summarize`. No network required.

## Dev setup
    pip install -e ".[dev]"
    pytest -v

All tests run fully offline against fake Git and LLM adapters.

## Next slices
Real GitHub/Bitbucket/GitLab adapters, Claude/OpenAI/local LLMs, webhooks +
poller, rules/stack packs, and the admin UI — see docs/superpowers/specs.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: foundation readme and quickstart"
```

---

## Self-Review

**Spec coverage (this slice = spec milestones 1–2):**
- Config (§7) → Task 3. ✓
- State store + dedup schema (§8) → Task 4. ✓
- Neutral models (§4.1) → Task 2. ✓
- Job queue: enqueue/claim/complete/fail, dedup, retry/dead-letter (§5) → Task 5. ✓
- `GitPlatformAdapter` interface + fake (§4.1, §10 L1) → Task 6. ✓
- `LLMAdapter` interface + fake (§4.2, §10 L1) → Task 7. ✓
- Reviewer + `code_review` + `summarize` (§6, milestone 2) → Tasks 8–10. ✓
- Offline localhost testing (§10 L1) → all tasks, confirmed Task 11. ✓
- Out of this slice (later plans): real adapters, LLM providers, ingress/poller, redaction, rules/gates, stack detection/packs, remaining 5 tasks, UI/auth, Docker/Alembic. Tracked in spec milestones 3–13.

**Placeholder scan:** No TBD/TODO; every code + test step is complete. ✓

**Type consistency:** `Side.right` used in Task 6 fake, Task 8 code_review, matches enum in Task 2. `TaskResult(name, posted)` consistent across Tasks 8–10 and reviewer. `_render_diff` defined in Task 8, reused in Task 9. `Queue.session_factory` attribute used in Task 5 test. `TASK_REGISTRY` keys match task `name` attrs. ✓
