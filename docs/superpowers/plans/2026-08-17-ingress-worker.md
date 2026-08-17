# PR Review Agent — Ingress, Worker & Poller Implementation Plan (Plan 3 of N)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the agent autonomous — a worker that claims queued jobs and runs the reviewer against real adapters, a FastAPI webhook ingress that enqueues jobs from GitHub push/PR events (HMAC-verified), and a poller that finds open PRs on an interval as a firewall-friendly fallback. Wire them into a runnable `app/main.py`.

**Architecture:** Ingress and poller are *producers* — they turn PR events into queued jobs (one per enabled task, deduped by the Plan 1 queue). The worker is the *consumer* — it claims a job, builds the git + llm adapters from config, runs that single task via the existing `Reviewer`, and marks the job done or failed. All three share the DB-backed queue, so producers and consumer are decoupled and horizontally scalable. Everything is tested offline: FastAPI `TestClient` for ingress, injected `MockTransport` for the worker/poller adapters, fakes for the queue where useful.

**Tech Stack:** Python 3.11+, FastAPI + Starlette `TestClient`, uvicorn (serving only), APScheduler (poller scheduling in `main` only), httpx (existing). Existing: SQLAlchemy, pydantic, pyyaml.

## Global Constraints

- Python 3.11+ (`from __future__ import annotations`).
- **No network in tests.** Ingress tested via `fastapi.testclient.TestClient`; worker/poller adapters via injected `httpx.MockTransport`; queue via real in-memory SQLite or the existing fakes.
- Producers (ingress, poller) only enqueue; the worker is the only component that calls adapters to post to a platform. This separation is not to be collapsed.
- Jobs are enqueued one-per-task using the existing `Queue.enqueue_event`; dedup by `(platform, repo, pr, head_sha, task)` is already enforced — do not re-implement it.
- Webhook signature verification uses HMAC-SHA256 (`hmac.compare_digest`); a request failing verification returns HTTP 401 and enqueues nothing.
- The worker builds adapters per job using the Plan 2 factories; on any exception it calls `Queue.fail(job.id, str(e))` (which handles retry/dead-letter) and never crashes the loop.
- Secrets (webhook secret, tokens, keys) come from config/env; never logged, never in responses.
- Every code change lands via TDD: failing test first, minimal impl, green, commit.

---

## File Structure

```
app/
  config.py                 # MODIFY: add IngressConfig, PollerConfig to Settings; find_repo(), resolve_tasks()
  ingress/
    __init__.py
    security.py             # verify_github_signature(secret, body, header) -> bool
    events.py               # parse_github_event(payload, event_type) -> Event | None
    app.py                  # create_app(settings, queue, verify=True) -> FastAPI
  worker.py                 # process_one(queue, settings, transport_git=None, transport_llm=None) -> bool
  poller.py                 # poll_once(settings, queue, adapter_for=None) -> int
  main.py                   # build_app(settings) + run() assembly
  git/base.py               # MODIFY: add abstract list_open_prs
  git/github.py             # MODIFY: implement list_open_prs
  git/fake.py               # MODIFY: implement list_open_prs
tests/
  test_ingress_security.py
  test_ingress_events.py
  test_list_open_prs.py
  test_worker.py
  test_ingress_app.py
  test_poller.py
  test_main_wiring.py
```

Dependency adds in `pyproject.toml`: `fastapi>=0.110`, `uvicorn>=0.29`, `apscheduler>=3.10`.

---

### Task 1: Dependencies, config extension, webhook signature verify

**Files:**
- Modify: `pyproject.toml` (add fastapi, uvicorn, apscheduler)
- Modify: `app/config.py` (add `IngressConfig`, `PollerConfig`, extend `Settings`)
- Create: `app/ingress/__init__.py`
- Create: `app/ingress/security.py`
- Test: `tests/test_ingress_security.py`
- Test: `tests/test_config.py` (add one case for the new config blocks)

**Interfaces:**
- Consumes: existing config.
- Produces:
  - `class IngressConfig(BaseModel)`: `enabled: bool = True`, `webhook_secret: str = ""`.
  - `class PollerConfig(BaseModel)`: `enabled: bool = True`, `interval_seconds: int = 60`.
  - `Settings` gains `ingress: IngressConfig = IngressConfig()` and `poller: PollerConfig = PollerConfig()`; `load_settings` reads optional `ingress:` and `poller:` YAML blocks (absent → defaults).
  - `verify_github_signature(secret: str, body: bytes, header: str | None) -> bool` — computes `sha256=` + HMAC-SHA256 hex of `body` keyed by `secret`; constant-time compares to `header`; returns False if header missing/malformed.

- [ ] **Step 1: Write the failing test**

`tests/test_ingress_security.py`:
```python
import hashlib
import hmac
from app.ingress.security import verify_github_signature


def _sig(secret, body):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_valid_signature_passes():
    body = b'{"a":1}'
    assert verify_github_signature("s3cret", body, _sig("s3cret", body)) is True


def test_wrong_secret_fails():
    body = b'{"a":1}'
    assert verify_github_signature("s3cret", body, _sig("other", body)) is False


def test_missing_header_fails():
    assert verify_github_signature("s3cret", b"{}", None) is False


def test_malformed_header_fails():
    assert verify_github_signature("s3cret", b"{}", "garbage") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingress_security.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ingress'`

- [ ] **Step 3: Write minimal implementation**

Add to `pyproject.toml` dependencies: `"fastapi>=0.110",`, `"uvicorn>=0.29",`, `"apscheduler>=3.10",` then `pip install -e ".[dev]"`.

In `app/config.py`, add the two models and extend `Settings` + `load_settings`:
```python
class IngressConfig(BaseModel):
    enabled: bool = True
    webhook_secret: str = ""


class PollerConfig(BaseModel):
    enabled: bool = True
    interval_seconds: int = 60


class Settings(BaseModel):
    llm: LLMConfig
    store: StoreConfig
    defaults_tasks: list[str]
    repos: list[RepoConfig]
    ingress: IngressConfig = IngressConfig()
    poller: PollerConfig = PollerConfig()
```
In `load_settings`, when constructing `Settings(...)`, add:
```python
            ingress=IngressConfig(**raw.get("ingress", {})),
            poller=PollerConfig(**raw.get("poller", {})),
```

`app/ingress/__init__.py`: (empty)

`app/ingress/security.py`:
```python
from __future__ import annotations

import hashlib
import hmac


def verify_github_signature(secret: str, body: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)
```

- [ ] **Step 4: Run tests to verify they pass**

Add to `tests/test_config.py`:
```python
def test_ingress_and_poller_defaults(tmp_path):
    path = _write(tmp_path, """
llm: {provider: fake, model: fake}
store: {url: 'sqlite:///:memory:'}
defaults: {tasks: [code_review]}
repos: []
""")
    s = load_settings(path, env={})
    assert s.ingress.enabled is True
    assert s.poller.interval_seconds == 60
```

Run: `pip install -e ".[dev]" && pytest tests/test_ingress_security.py tests/test_config.py -v`
Expected: PASS (4 security + existing config + 1 new)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml app/config.py app/ingress/__init__.py app/ingress/security.py tests/test_ingress_security.py tests/test_config.py
git commit -m "feat: ingress/poller config and webhook signature verify"
```

---

### Task 2: GitHub webhook event parser

**Files:**
- Create: `app/ingress/events.py`
- Test: `tests/test_ingress_events.py`

**Interfaces:**
- Consumes: `Event`, `Platform` from `app.models`.
- Produces:
  - `parse_github_event(payload: dict, event_type: str | None) -> Event | None` — for `event_type == "pull_request"` and `payload["action"]` in `{opened, synchronize, reopened}`, returns `Event(platform=Platform.github, repo=payload["repository"]["full_name"], pr_number=payload["pull_request"]["number"], head_sha=payload["pull_request"]["head"]["sha"], action=payload["action"])`; any other event type or action returns `None`.

- [ ] **Step 1: Write the failing test**

`tests/test_ingress_events.py`:
```python
from app.ingress.events import parse_github_event
from app.models import Platform


def _payload(action="opened"):
    return {
        "action": action,
        "repository": {"full_name": "o/r"},
        "pull_request": {"number": 7, "head": {"sha": "abc"}},
    }


def test_opened_pull_request_maps_to_event():
    ev = parse_github_event(_payload("opened"), "pull_request")
    assert ev.platform == Platform.github
    assert ev.repo == "o/r"
    assert ev.pr_number == 7
    assert ev.head_sha == "abc"
    assert ev.action == "opened"


def test_synchronize_is_accepted():
    assert parse_github_event(_payload("synchronize"), "pull_request") is not None


def test_closed_action_ignored():
    assert parse_github_event(_payload("closed"), "pull_request") is None


def test_non_pr_event_ignored():
    assert parse_github_event(_payload(), "issues") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingress_events.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ingress.events'`

- [ ] **Step 3: Write minimal implementation**

`app/ingress/events.py`:
```python
from __future__ import annotations

from app.models import Event, Platform

_ACCEPTED = {"opened", "synchronize", "reopened"}


def parse_github_event(payload: dict, event_type: str | None) -> Event | None:
    if event_type != "pull_request":
        return None
    if payload.get("action") not in _ACCEPTED:
        return None
    pr = payload["pull_request"]
    return Event(
        platform=Platform.github,
        repo=payload["repository"]["full_name"],
        pr_number=pr["number"],
        head_sha=pr["head"]["sha"],
        action=payload["action"],
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ingress_events.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add app/ingress/events.py tests/test_ingress_events.py
git commit -m "feat: GitHub webhook event parser"
```

---

### Task 3: list_open_prs across the git adapter interface

**Files:**
- Modify: `app/git/base.py` (add abstract `list_open_prs`)
- Modify: `app/git/github.py` (implement `list_open_prs`)
- Modify: `app/git/fake.py` (implement `list_open_prs`)
- Test: `tests/test_list_open_prs.py`

**Interfaces:**
- Consumes: `PR`, `Platform`.
- Produces:
  - `GitPlatformAdapter.list_open_prs(repo: str) -> list[PR]` (new abstract method).
  - `GitHubAdapter.list_open_prs` — GET `/repos/{repo}/pulls?state=open`; each row → `PR(platform=Platform.github, repo=repo, number=row["number"], head_sha=row["head"]["sha"])`.
  - `FakeGitAdapter.list_open_prs` — returns a `PR` for each key in its seed dict (`platform=Platform.github`, `repo`, `number`, `head_sha` from the seeded `PRMeta.head_sha`).

- [ ] **Step 1: Write the failing test**

`tests/test_list_open_prs.py`:
```python
import httpx
from app.git.github import GitHubAdapter
from app.git.fake import FakeGitAdapter
from app.models import Platform
from tests.fixtures import sample_meta, sample_diff


def test_github_list_open_prs():
    def handler(request):
        assert request.url.path == "/repos/o/r/pulls"
        assert request.url.params.get("state") == "open"
        return httpx.Response(200, json=[
            {"number": 1, "head": {"sha": "s1"}},
            {"number": 2, "head": {"sha": "s2"}},
        ])
    a = GitHubAdapter("o/r", "t", transport=httpx.MockTransport(handler))
    prs = a.list_open_prs("o/r")
    assert [p.number for p in prs] == [1, 2]
    assert prs[0].platform == Platform.github
    assert prs[1].head_sha == "s2"


def test_fake_list_open_prs():
    a = FakeGitAdapter(seed={("o/r", 1): (sample_meta(head_sha="H1"), sample_diff())})
    prs = a.list_open_prs("o/r")
    assert len(prs) == 1
    assert prs[0].number == 1
    assert prs[0].head_sha == "H1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_list_open_prs.py -v`
Expected: FAIL — `AttributeError`/`TypeError` (method missing / adapters abstract).

- [ ] **Step 3: Write minimal implementation**

In `app/git/base.py`, add the abstract method (alongside the others):
```python
    @abstractmethod
    def list_open_prs(self, repo: str) -> list["PR"]: ...
```
Ensure `PR` is imported in `base.py`: add `PR` to the `from app.models import ...` line.

In `app/git/github.py`, add:
```python
    def list_open_prs(self, repo) -> list[PR]:
        rows = self._get(f"/repos/{repo}/pulls?state=open")
        return [PR(platform=Platform.github, repo=repo, number=r["number"],
                   head_sha=r["head"]["sha"]) for r in rows]
```
Add `PR` and `Platform` to the imports in `github.py` (Platform already imported; add `PR`).

In `app/git/fake.py`, add:
```python
    def list_open_prs(self, repo) -> list[PR]:
        out = []
        for (r, number), (meta, _diff) in self._seed.items():
            if r == repo:
                out.append(PR(platform=Platform.github, repo=r, number=number,
                              head_sha=meta.head_sha))
        return out
```
Add `PR` and `Platform` to the imports in `fake.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_list_open_prs.py tests/test_fake_git.py tests/test_github_read.py -v`
Expected: PASS (new 2 + existing fake/github tests still green — the interface addition didn't break instantiation because both concretes now implement it).

- [ ] **Step 5: Commit**

```bash
git add app/git/base.py app/git/github.py app/git/fake.py tests/test_list_open_prs.py
git commit -m "feat: list_open_prs on git adapter interface, github, and fake"
```

---

### Task 4: Worker — process one job

**Files:**
- Modify: `app/config.py` (add `find_repo` helper)
- Create: `app/worker.py`
- Test: `tests/test_worker.py`

**Interfaces:**
- Consumes: `Queue`, `Settings`, `RepoConfig`, `build_git_adapter`, `build_llm_adapter`, `Reviewer`, `Platform`.
- Produces:
  - `find_repo(settings, platform: str, full_name: str) -> RepoConfig | None` (in `app/config.py`) — matches a repo in `settings.repos` by `platform.value == platform` and `full_name`.
  - `process_one(queue, settings, transport_git=None, transport_llm=None) -> bool` (in `app/worker.py`) — claims one job; if none, returns `False`. Otherwise builds the git adapter (via `build_git_adapter(repo_cfg, transport=transport_git)`) and llm adapter (via `build_llm_adapter(settings.llm, transport=transport_llm)`), runs `Reviewer(git, llm).review(job.repo, job.pr_number, [job.task])`, then `queue.complete(job.id)`. On any exception (including missing repo config) calls `queue.fail(job.id, str(e))`. Always returns `True` when a job was claimed.

- [ ] **Step 1: Write the failing test**

`tests/test_worker.py`:
```python
import httpx
from app.store.db import make_engine, make_session_factory, init_db
from app.queue import Queue
from app.config import Settings, LLMConfig, StoreConfig, RepoConfig
from app.models import Platform
from app.store.tables import Job, DeadLetter
from app.worker import process_one


def _settings():
    return Settings(
        llm=LLMConfig(provider="claude", model="m", api_key="k"),
        store=StoreConfig(url="sqlite:///:memory:"),
        defaults_tasks=["summarize"],
        repos=[RepoConfig(platform=Platform.github, full_name="o/r", token="t")],
    )


def _queue():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    return Queue(make_session_factory(engine))


def _gh(request):
    p = request.url.path
    if p == "/repos/o/r/pulls/1":
        return httpx.Response(200, json={"title": "t", "body": "", "user": {"login": "a"},
                                         "base": {"sha": "b"}, "head": {"sha": "H"}, "labels": []})
    if p == "/repos/o/r/commits/H/status":
        return httpx.Response(200, json={"state": "success"})
    if p == "/repos/o/r/pulls/1/files":
        return httpx.Response(200, json=[{"filename": "a.py", "patch": "@@ +x",
                                          "additions": 1, "deletions": 0, "status": "modified"}])
    if p == "/repos/o/r/issues/1/comments":
        return httpx.Response(201, json={"id": 1})
    return httpx.Response(404, text=p)


def _claude(request):
    return httpx.Response(200, json={"content": [{"type": "text", "text": "Summary."}],
                                     "usage": {"input_tokens": 1, "output_tokens": 1}})


def test_process_one_completes_job():
    q = _queue()
    q.enqueue("github", "o/r", 1, "H", "summarize")
    handled = process_one(q, _settings(),
                          transport_git=httpx.MockTransport(_gh),
                          transport_llm=httpx.MockTransport(_claude))
    assert handled is True
    with q.session_factory() as s:
        assert s.get(Job, 1).status == "done"


def test_process_one_no_jobs_returns_false():
    assert process_one(_queue(), _settings()) is False


def test_process_one_missing_repo_fails_job():
    q = _queue()
    q.enqueue("github", "unknown/repo", 1, "H", "summarize")
    process_one(q, _settings())
    with q.session_factory() as s:
        job = s.get(Job, 1)
    # retried back to pending (attempts<max) with error recorded
    assert job.error is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_worker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.worker'`

- [ ] **Step 3: Write minimal implementation**

In `app/config.py`, add:
```python
def find_repo(settings: "Settings", platform: str, full_name: str) -> RepoConfig | None:
    for r in settings.repos:
        if r.platform.value == platform and r.full_name == full_name:
            return r
    return None
```

`app/worker.py`:
```python
from __future__ import annotations

from app.config import find_repo
from app.git.factory import build_git_adapter
from app.llm.factory import build_llm_adapter
from app.reviewer import Reviewer


def process_one(queue, settings, transport_git=None, transport_llm=None) -> bool:
    job = queue.claim()
    if job is None:
        return False
    try:
        repo_cfg = find_repo(settings, job.platform, job.repo)
        if repo_cfg is None:
            raise ValueError(f"No repo config for {job.platform}:{job.repo}")
        git = build_git_adapter(repo_cfg, transport=transport_git)
        llm = build_llm_adapter(settings.llm, transport=transport_llm)
        Reviewer(git, llm).review(job.repo, job.pr_number, [job.task])
        queue.complete(job.id)
    except Exception as e:  # worker never crashes the loop
        queue.fail(job.id, str(e))
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_worker.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/config.py app/worker.py tests/test_worker.py
git commit -m "feat: worker process_one + find_repo helper"
```

---

### Task 5: Ingress FastAPI app

**Files:**
- Modify: `app/config.py` (add `resolve_tasks` helper)
- Create: `app/ingress/app.py`
- Test: `tests/test_ingress_app.py`

**Interfaces:**
- Consumes: `Settings`, `Queue`, `verify_github_signature`, `parse_github_event`, `find_repo`, FastAPI.
- Produces:
  - `resolve_tasks(settings, repo_cfg) -> list[str]` (in `app/config.py`) — `repo_cfg.tasks` if not None else `settings.defaults_tasks`.
  - `create_app(settings, queue, verify: bool = True) -> FastAPI`:
    - `GET /health` → `{"status": "ok"}`.
    - `POST /webhook/{platform}` — reads raw body; if `verify` and `settings.ingress.webhook_secret` set, checks `X-Hub-Signature-256` via `verify_github_signature`, returns 401 on failure; parses body JSON; `parse_github_event(payload, X-GitHub-Event)`; if `None` → `{"enqueued": 0}`; else find repo config (unknown repo → `{"enqueued": 0}`), `resolve_tasks`, `queue.enqueue_event(event, tasks)`, return `{"enqueued": <count>}`.

- [ ] **Step 1: Write the failing test**

`tests/test_ingress_app.py`:
```python
import hashlib
import hmac
import json
from fastapi.testclient import TestClient
from app.store.db import make_engine, make_session_factory, init_db
from app.queue import Queue
from app.config import Settings, LLMConfig, StoreConfig, RepoConfig, IngressConfig
from app.models import Platform
from app.ingress.app import create_app


def _queue():
    engine = make_engine("sqlite:///:memory:")
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingress_app.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ingress.app'`

- [ ] **Step 3: Write minimal implementation**

In `app/config.py`, add:
```python
def resolve_tasks(settings: "Settings", repo_cfg: RepoConfig) -> list[str]:
    return repo_cfg.tasks if repo_cfg.tasks is not None else settings.defaults_tasks
```

`app/ingress/app.py`:
```python
from __future__ import annotations

import json

from fastapi import FastAPI, Request, Response

from app.config import find_repo, resolve_tasks
from app.ingress.events import parse_github_event
from app.ingress.security import verify_github_signature


def create_app(settings, queue, verify: bool = True) -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/webhook/{platform}")
    async def webhook(platform: str, request: Request):
        body = await request.body()
        secret = settings.ingress.webhook_secret
        if verify and secret:
            sig = request.headers.get("X-Hub-Signature-256")
            if not verify_github_signature(secret, body, sig):
                return Response(status_code=401)
        payload = json.loads(body)
        event = parse_github_event(payload, request.headers.get("X-GitHub-Event"))
        if event is None:
            return {"enqueued": 0}
        repo_cfg = find_repo(settings, event.platform.value, event.repo)
        if repo_cfg is None:
            return {"enqueued": 0}
        jobs = queue.enqueue_event(event, resolve_tasks(settings, repo_cfg))
        return {"enqueued": len(jobs)}

    return app
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ingress_app.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add app/config.py app/ingress/app.py tests/test_ingress_app.py
git commit -m "feat: FastAPI webhook ingress + resolve_tasks"
```

---

### Task 6: Poller

**Files:**
- Create: `app/poller.py`
- Test: `tests/test_poller.py`

**Interfaces:**
- Consumes: `Settings`, `Queue`, `build_git_adapter`, `resolve_tasks`, `Event`, `Platform`.
- Produces:
  - `poll_once(settings, queue, adapter_for=None) -> int` — for each `repo_cfg` in `settings.repos`, obtain an adapter (`adapter_for(repo_cfg)` if provided — the test seam — else `build_git_adapter(repo_cfg)`), call `list_open_prs(repo_cfg.full_name)`, and for each PR enqueue via `queue.enqueue_event(Event(platform=repo_cfg.platform, repo=repo_cfg.full_name, pr_number=pr.number, head_sha=pr.head_sha, action="poll"), resolve_tasks(settings, repo_cfg))`. Returns the total number of jobs enqueued across all repos. A repo whose adapter raises is skipped (logged via the returned count not counting it) — catch exceptions per repo so one bad repo doesn't stop the sweep.

- [ ] **Step 1: Write the failing test**

`tests/test_poller.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_poller.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.poller'`

- [ ] **Step 3: Write minimal implementation**

`app/poller.py`:
```python
from __future__ import annotations

from app.config import resolve_tasks
from app.git.factory import build_git_adapter
from app.models import Event


def poll_once(settings, queue, adapter_for=None) -> int:
    total = 0
    for repo_cfg in settings.repos:
        try:
            adapter = adapter_for(repo_cfg) if adapter_for else build_git_adapter(repo_cfg)
            prs = adapter.list_open_prs(repo_cfg.full_name)
            tasks = resolve_tasks(settings, repo_cfg)
            for pr in prs:
                event = Event(platform=repo_cfg.platform, repo=repo_cfg.full_name,
                              pr_number=pr.number, head_sha=pr.head_sha, action="poll")
                total += len(queue.enqueue_event(event, tasks))
        except Exception:
            continue  # one bad repo must not stop the sweep
    return total
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_poller.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/poller.py tests/test_poller.py
git commit -m "feat: poller poll_once with per-repo isolation"
```

---

### Task 7: Assembly (main.py), README, full suite

**Files:**
- Create: `app/main.py`
- Modify: `README.md`
- Test: `tests/test_main_wiring.py`

**Interfaces:**
- Consumes: `Settings`, `load_settings`, `Queue`, `make_engine/make_session_factory/init_db`, `create_app`, `process_one`, `poll_once`.
- Produces:
  - `build_app(settings) -> tuple[FastAPI, Queue]` — creates the engine (from `settings.store.url`), `init_db`, a `Queue`, and returns `(create_app(settings, queue), queue)`. This is the unit-testable assembly seam.
  - `run(config_path="config.yaml") -> None` — loads settings, calls `build_app`, starts a background worker thread that loops `process_one` (sleeping briefly when it returns False), schedules `poll_once` on `settings.poller.interval_seconds` via APScheduler when `settings.poller.enabled`, and serves the app with uvicorn on `0.0.0.0:8000`. `run` is the process entrypoint and is NOT exercised by unit tests (it blocks on the server); only `build_app` is tested.

- [ ] **Step 1: Write the failing test**

`tests/test_main_wiring.py`:
```python
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.config import Settings, LLMConfig, StoreConfig
from app.main import build_app


def _settings():
    return Settings(llm=LLMConfig(provider="fake"),
                    store=StoreConfig(url="sqlite:///:memory:"),
                    defaults_tasks=["summarize"], repos=[])


def test_build_app_returns_app_and_queue():
    app, queue = build_app(_settings())
    assert isinstance(app, FastAPI)
    # queue is usable: enqueue then claim
    queue.enqueue("github", "o/r", 1, "s", "summarize")
    assert queue.claim() is not None


def test_built_app_health_ok():
    app, _ = build_app(_settings())
    assert TestClient(app).get("/health").json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main_wiring.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Write minimal implementation**

`app/main.py`:
```python
from __future__ import annotations

import time
import threading

from app.config import load_settings
from app.ingress.app import create_app
from app.poller import poll_once
from app.queue import Queue
from app.store.db import make_engine, make_session_factory, init_db
from app.worker import process_one


def build_app(settings):
    engine = make_engine(settings.store.url)
    init_db(engine)
    queue = Queue(make_session_factory(engine))
    return create_app(settings, queue), queue


def _worker_loop(queue, settings, stop):
    while not stop.is_set():
        if not process_one(queue, settings):
            time.sleep(1.0)


def run(config_path: str = "config.yaml") -> None:  # pragma: no cover
    import uvicorn
    from apscheduler.schedulers.background import BackgroundScheduler

    settings = load_settings(config_path)
    app, queue = build_app(settings)

    stop = threading.Event()
    worker = threading.Thread(target=_worker_loop, args=(queue, settings, stop), daemon=True)
    worker.start()

    scheduler = None
    if settings.poller.enabled:
        scheduler = BackgroundScheduler()
        scheduler.add_job(lambda: poll_once(settings, queue),
                          "interval", seconds=settings.poller.interval_seconds)
        scheduler.start()

    try:
        uvicorn.run(app, host="0.0.0.0", port=8000)
    finally:
        stop.set()
        if scheduler:
            scheduler.shutdown(wait=False)


if __name__ == "__main__":  # pragma: no cover
    run()
```

- [ ] **Step 4: Run test + full suite**

Run: `pytest tests/test_main_wiring.py -v && pytest -q`
Expected: PASS — 2 wiring tests + whole suite green (Plan 1+2 tests plus all Plan 3 tests), pristine output, zero network.

- [ ] **Step 5: Append README + commit**

Append to `README.md`:
```markdown
## Running the service (slice 3)
The agent runs autonomously: a worker drains the job queue, a FastAPI webhook
ingress enqueues jobs from GitHub PR events, and a poller sweeps open PRs on an
interval as a fallback.

    cp config.example.yaml config.yaml    # set env vars first
    python -m app.main                    # serves on :8000, starts worker + poller

- `POST /webhook/github` — point a GitHub webhook here (content-type JSON,
  secret = `ingress.webhook_secret`); PR `opened`/`synchronize`/`reopened`
  events enqueue review jobs.
- `GET /health` — liveness.
- Poller runs every `poller.interval_seconds` when `poller.enabled`.

All ingress/worker/poller logic is tested offline (FastAPI TestClient +
httpx.MockTransport); no network in the test suite.
```

```bash
git add app/main.py README.md tests/test_main_wiring.py
git commit -m "feat: main assembly (worker loop + poller schedule + server)"
```

---

## Self-Review

**Spec coverage (this slice = spec milestone 8, ingress/poller + the worker that §5 data flow implies):**
- Ingress webhooks + HMAC signature verify (§3, §5.1) → Tasks 1,2,5. ✓
- Poller fallback (§3 architecture, §5.1) → Task 6. ✓
- Worker: claim → build adapters → run task → complete/fail (§5 steps 4-9) → Task 4. ✓
- `list_open_prs` needed by poller (deferred from Plan 2) → Task 3. ✓
- Config for ingress/poller + repo/task resolution (§7) → Tasks 1,4,5. ✓
- Assembly / deploy entrypoint (§9, minus Docker) → Task 7. ✓
- Offline testability (§10) → all tasks (TestClient + MockTransport). ✓
- Deferred to later slices: redaction before LLM (§5 step 6), rules/gates, stack packs, remaining 5 tasks incl. `qa_reply` (which needs comment-event parsing), Bitbucket/GitLab, admin UI/auth, Dockerfile/compose/Alembic. Producer/consumer seams are in place so these layer on cleanly.

**Placeholder scan:** No TBD/TODO. `run()` is marked `# pragma: no cover` because it blocks on the server; `build_app` is the tested seam — this is an explicit, justified boundary, not a placeholder.

**Type consistency:** `Event(platform, repo, pr_number, head_sha, action[, comment_body])` used consistently in events parser (Task 2), worker path via queue (Task 4), poller (Task 6) — matches the Plan 1 dataclass. `PR(platform, repo, number, head_sha)` used in Task 3 github + fake + poller. `find_repo(settings, platform: str, full_name)` (Task 4) called by worker with `job.platform` (a str column) and by ingress with `event.platform.value` (Task 5) — both strings, consistent. `resolve_tasks(settings, repo_cfg)` (Task 5) used by ingress + poller. `Queue.enqueue_event(event, tasks)` returns the created jobs list — `len(...)` used for counts in ingress + poller, matching Plan 1's signature. `create_app(settings, queue, verify=True)` used in Tasks 5,7.
