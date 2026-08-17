# PR Review Agent — Real Adapters Implementation Plan (Plan 2 of N)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fakes with real, drop-in `GitPlatformAdapter` (GitHub) and `LLMAdapter` (Claude, OpenAI, local) concretes, plus factories that build them from config — so the existing reviewer runs `code_review` + `summarize` against a real GitHub PR and a real LLM. All adapters are implemented over `httpx` and tested offline with `httpx.MockTransport` (zero network in tests).

**Architecture:** Each concrete adapter maps a provider's HTTP request/response to the neutral types from Plan 1. GitHub uses the REST v3 API; Claude uses `/v1/messages`; OpenAI and local use `/v1/chat/completions` (local = OpenAI-compatible endpoint via `base_url`). Factories select a concrete from config strings. The neutral interfaces and the reviewer are unchanged — this slice only adds implementations behind the existing abstractions.

**Tech Stack:** Python 3.11+, httpx, pytest (with `httpx.MockTransport`). Existing: SQLAlchemy, pydantic, pyyaml.

## Global Constraints

- Python 3.11+ (`from __future__ import annotations`).
- **No network in tests.** Every adapter test injects an `httpx.MockTransport` (or a mock `httpx.Client`) — never a live host.
- Concrete adapters map provider payloads to/from the neutral types in `app/models.py` and `app/llm/base.py`; the neutral interfaces (`GitPlatformAdapter`, `LLMAdapter`) are NOT modified in this slice.
- New concretes must be drop-in: `GitHubAdapter` implements exactly the 7 abstract `GitPlatformAdapter` methods; LLM adapters implement `complete` + `count_tokens`.
- `count_tokens` is an approximation (`len(text.split())`) across all LLM adapters in this slice; exact tokenization is deferred.
- HTTP errors (non-2xx) raise a typed `AdapterError` with status + body; callers (queue retry) handle it.
- Secrets (tokens, api keys) come from config/env, never hardcoded, never logged.
- `repo` is the string `"owner/name"`; adapters split it as needed.
- Every code change lands via TDD: failing test first, minimal impl, green, commit.

---

## File Structure

```
app/
  errors.py                 # AdapterError
  http.py                   # build_client(base_url, headers, transport=None) -> httpx.Client
  git/
    github.py               # GitHubAdapter(GitPlatformAdapter)
    factory.py              # build_git_adapter(repo_config) -> GitPlatformAdapter
  llm/
    http_llm.py             # _post_json helper shared by llm adapters
    claude.py               # ClaudeAdapter(LLMAdapter)
    openai.py               # OpenAIAdapter(LLMAdapter)
    local.py                # LocalAdapter(OpenAIAdapter)
    factory.py              # build_llm_adapter(llm_config) -> LLMAdapter
  config.py                 # MODIFY: LLMConfig gains api_key, base_url
tests/
  test_errors.py
  test_github_read.py
  test_github_write.py
  test_git_factory.py
  test_claude.py
  test_openai_local.py
  test_llm_factory.py
  test_integration_real.py
  config.example.yaml       # example wired config (also copied to repo root)
```

Dependency add: `httpx>=0.27` in `pyproject.toml`.

---

### Task 1: httpx dependency, AdapterError, HTTP client helper

**Files:**
- Modify: `pyproject.toml` (add `httpx>=0.27`)
- Create: `app/errors.py`
- Create: `app/http.py`
- Test: `tests/test_errors.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class AdapterError(Exception)` with `status: int`, `body: str`; `__str__` includes both.
  - `build_client(base_url: str, headers: dict[str, str], transport=None) -> httpx.Client` — returns a configured `httpx.Client`; when `transport` is provided (an `httpx.MockTransport`), it is used (this is the test seam).
  - `raise_for_status(resp: httpx.Response) -> None` — raises `AdapterError(resp.status_code, resp.text)` on non-2xx, else returns.

- [ ] **Step 1: Write the failing test**

`tests/test_errors.py`:
```python
import httpx
import pytest
from app.errors import AdapterError
from app.http import build_client, raise_for_status


def test_adapter_error_message():
    e = AdapterError(404, "not found")
    assert e.status == 404
    assert "404" in str(e) and "not found" in str(e)


def test_raise_for_status_raises_on_4xx():
    resp = httpx.Response(403, text="forbidden")
    with pytest.raises(AdapterError) as ei:
        raise_for_status(resp)
    assert ei.value.status == 403


def test_raise_for_status_ok_on_200():
    raise_for_status(httpx.Response(200, text="ok"))  # no raise


def test_build_client_uses_transport():
    def handler(request):
        return httpx.Response(200, json={"seen": str(request.url)})
    client = build_client("https://api.example.com", {"X-Test": "1"},
                          transport=httpx.MockTransport(handler))
    r = client.get("/ping")
    assert r.status_code == 200
    assert "api.example.com/ping" in r.json()["seen"]
    assert client.headers["X-Test"] == "1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_errors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.errors'`

- [ ] **Step 3: Write minimal implementation**

Add to `pyproject.toml` dependencies list: `"httpx>=0.27",` then run `pip install -e ".[dev]"`.

`app/errors.py`:
```python
from __future__ import annotations


class AdapterError(Exception):
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"HTTP {status}: {body}")
```

`app/http.py`:
```python
from __future__ import annotations

import httpx

from app.errors import AdapterError


def build_client(base_url: str, headers: dict[str, str], transport=None) -> httpx.Client:
    return httpx.Client(base_url=base_url, headers=headers, transport=transport,
                        timeout=30.0)


def raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code >= 300:
        raise AdapterError(resp.status_code, resp.text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pip install -e ".[dev]" && pytest tests/test_errors.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml app/errors.py app/http.py tests/test_errors.py
git commit -m "feat: httpx client helper and AdapterError"
```

---

### Task 2: GitHubAdapter — read methods

**Files:**
- Create: `app/git/github.py`
- Test: `tests/test_github_read.py`

**Interfaces:**
- Consumes: `GitPlatformAdapter`, neutral types, `build_client`, `raise_for_status`.
- Produces:
  - `class GitHubAdapter(GitPlatformAdapter)` constructed as `GitHubAdapter(repo_owner_name: str, token: str, transport=None, api_base="https://api.github.com")`. Stores an `httpx.Client` from `build_client` with `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`.
  - `get_pr_meta(repo, pr_number) -> PRMeta` — GET `/repos/{repo}/pulls/{n}`; maps title, body, `user.login`→author, `base.sha`, `head.sha`, `labels[].name`; `linked_issues` = `#\d+` matches in body; `ci_passed` from GET `/repos/{repo}/commits/{head_sha}/status` (`state=="success"` → True, `"pending"`/none → None, else False).
  - `get_diff(repo, pr_number) -> Diff` — GET `/repos/{repo}/pulls/{n}/files`; each file → `FileChange(path=filename, patch=patch or "", additions, deletions, status)`.

Note: `repo` passed to methods equals the adapter's repo; the parameter is kept for interface conformance and used in the URL.

- [ ] **Step 1: Write the failing test**

`tests/test_github_read.py`:
```python
import httpx
from app.git.github import GitHubAdapter


def _adapter(handler):
    return GitHubAdapter("o/r", "tok", transport=httpx.MockTransport(handler))


def test_get_pr_meta_maps_fields():
    def handler(request):
        if request.url.path == "/repos/o/r/pulls/1":
            return httpx.Response(200, json={
                "title": "Add x", "body": "Fixes #7",
                "user": {"login": "alice"},
                "base": {"sha": "b1"}, "head": {"sha": "h1"},
                "labels": [{"name": "bug"}],
            })
        if request.url.path == "/repos/o/r/commits/h1/status":
            return httpx.Response(200, json={"state": "success"})
        return httpx.Response(404, text="nope")

    meta = _adapter(handler).get_pr_meta("o/r", 1)
    assert meta.title == "Add x"
    assert meta.author == "alice"
    assert meta.head_sha == "h1"
    assert meta.labels == ["bug"]
    assert meta.linked_issues == ["#7"]
    assert meta.ci_passed is True


def test_get_diff_maps_files():
    def handler(request):
        assert request.url.path == "/repos/o/r/pulls/1/files"
        return httpx.Response(200, json=[
            {"filename": "a.py", "patch": "@@ -1 +1 @@", "additions": 2,
             "deletions": 1, "status": "modified"},
        ])

    diff = _adapter(handler).get_diff("o/r", 1)
    assert len(diff.files) == 1
    assert diff.files[0].path == "a.py"
    assert diff.total_changed_lines() == 3


def test_get_diff_handles_missing_patch():
    def handler(request):
        return httpx.Response(200, json=[
            {"filename": "bin.dat", "additions": 0, "deletions": 0, "status": "added"},
        ])
    diff = _adapter(handler).get_diff("o/r", 1)
    assert diff.files[0].patch == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_github_read.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.git.github'`

- [ ] **Step 3: Write minimal implementation**

`app/git/github.py`:
```python
from __future__ import annotations

import re

from app.git.base import GitPlatformAdapter
from app.http import build_client, raise_for_status
from app.models import PRMeta, Diff, FileChange, Comment, Verdict, Side

_ISSUE_REF = re.compile(r"#\d+")

_VERDICT_EVENT = {
    Verdict.approve: "APPROVE",
    Verdict.request_changes: "REQUEST_CHANGES",
    Verdict.comment: "COMMENT",
}


class GitHubAdapter(GitPlatformAdapter):
    def __init__(self, repo_owner_name: str, token: str, transport=None,
                 api_base: str = "https://api.github.com"):
        self.repo = repo_owner_name
        self._client = build_client(
            api_base,
            {"Authorization": f"Bearer {token}",
             "Accept": "application/vnd.github+json"},
            transport=transport,
        )

    def _get(self, path: str):
        resp = self._client.get(path)
        raise_for_status(resp)
        return resp.json()

    def _post(self, path: str, payload: dict):
        resp = self._client.post(path, json=payload)
        raise_for_status(resp)
        return resp.json()

    def get_pr_meta(self, repo, pr_number) -> PRMeta:
        pr = self._get(f"/repos/{repo}/pulls/{pr_number}")
        head_sha = pr["head"]["sha"]
        ci_passed = None
        status = self._get(f"/repos/{repo}/commits/{head_sha}/status")
        state = status.get("state")
        if state == "success":
            ci_passed = True
        elif state in ("failure", "error"):
            ci_passed = False
        body = pr.get("body") or ""
        return PRMeta(
            title=pr.get("title") or "",
            body=body,
            author=pr.get("user", {}).get("login", ""),
            base_sha=pr["base"]["sha"],
            head_sha=head_sha,
            labels=[l["name"] for l in pr.get("labels", [])],
            linked_issues=_ISSUE_REF.findall(body),
            ci_passed=ci_passed,
        )

    def get_diff(self, repo, pr_number) -> Diff:
        files = self._get(f"/repos/{repo}/pulls/{pr_number}/files")
        return Diff(files=[
            FileChange(path=f["filename"], patch=f.get("patch") or "",
                       additions=f.get("additions", 0),
                       deletions=f.get("deletions", 0),
                       status=f.get("status", "")）
            for f in files
        ])

    # write methods added in Task 3
    def post_comment(self, repo, pr_number, body) -> str:
        raise NotImplementedError

    def post_inline_comment(self, repo, pr_number, path, line, body, side: Side) -> str:
        raise NotImplementedError

    def set_review_verdict(self, repo, pr_number, verdict: Verdict, body) -> None:
        raise NotImplementedError

    def get_thread(self, repo, pr_number) -> list[Comment]:
        raise NotImplementedError

    def reply(self, repo, pr_number, in_reply_to, body) -> str:
        raise NotImplementedError
```

NOTE to implementer: the fullwidth `）` in the `get_diff` list comprehension above is a typo — use a normal ASCII `)`. Fix it when transcribing.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_github_read.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/git/github.py tests/test_github_read.py
git commit -m "feat: GitHubAdapter read methods (pr meta, diff)"
```

---

### Task 3: GitHubAdapter — write methods

**Files:**
- Modify: `app/git/github.py` (replace the 5 `NotImplementedError` stubs)
- Test: `tests/test_github_write.py`

**Interfaces:**
- Consumes: same as Task 2.
- Produces (replacing stubs):
  - `post_comment(repo, pr_number, body) -> str` — POST `/repos/{repo}/issues/{pr_number}/comments` `{body}`; returns `str(resp["id"])`.
  - `post_inline_comment(repo, pr_number, path, line, body, side) -> str` — POST `/repos/{repo}/pulls/{pr_number}/comments` `{body, path, line, side: side.name.upper(), commit_id}` where `commit_id` = head sha fetched via `get_pr_meta(...).head_sha`; returns `str(resp["id"])`.
  - `set_review_verdict(repo, pr_number, verdict, body) -> None` — POST `/repos/{repo}/pulls/{pr_number}/reviews` `{event: _VERDICT_EVENT[verdict], body}`.
  - `get_thread(repo, pr_number) -> list[Comment]` — GET `/repos/{repo}/issues/{pr_number}/comments`; map each to `Comment(id=str(id), author=user.login, body=body)`.
  - `reply(repo, pr_number, in_reply_to, body) -> str` — POST `/repos/{repo}/issues/{pr_number}/comments` `{body}` (thread reply as issue comment); returns `str(resp["id"])`.

- [ ] **Step 1: Write the failing test**

`tests/test_github_write.py`:
```python
import httpx
from app.git.github import GitHubAdapter
from app.models import Verdict, Side


def _adapter(handler):
    return GitHubAdapter("o/r", "tok", transport=httpx.MockTransport(handler))


def test_post_comment_returns_id():
    def handler(request):
        assert request.url.path == "/repos/o/r/issues/1/comments"
        assert request.method == "POST"
        return httpx.Response(201, json={"id": 555})
    assert _adapter(handler).post_comment("o/r", 1, "hi") == "555"


def test_post_inline_comment_sends_commit_and_side():
    seen = {}
    def handler(request):
        import json
        if request.url.path == "/repos/o/r/pulls/1":
            return httpx.Response(200, json={
                "title": "t", "body": "", "user": {"login": "a"},
                "base": {"sha": "b"}, "head": {"sha": "HEADSHA"}, "labels": [],
            })
        if request.url.path == "/repos/o/r/commits/HEADSHA/status":
            return httpx.Response(200, json={"state": "pending"})
        if request.url.path == "/repos/o/r/pulls/1/comments":
            seen.update(json.loads(request.content))
            return httpx.Response(201, json={"id": 9})
        return httpx.Response(404, text="x")
    cid = _adapter(handler).post_inline_comment("o/r", 1, "a.py", 3, "nit", Side.right)
    assert cid == "9"
    assert seen["commit_id"] == "HEADSHA"
    assert seen["side"] == "RIGHT"
    assert seen["path"] == "a.py" and seen["line"] == 3


def test_set_review_verdict_maps_event():
    seen = {}
    def handler(request):
        import json
        assert request.url.path == "/repos/o/r/pulls/1/reviews"
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"id": 1})
    _adapter(handler).set_review_verdict("o/r", 1, Verdict.request_changes, "please fix")
    assert seen["event"] == "REQUEST_CHANGES"
    assert seen["body"] == "please fix"


def test_get_thread_maps_comments():
    def handler(request):
        assert request.url.path == "/repos/o/r/issues/1/comments"
        return httpx.Response(200, json=[
            {"id": 1, "user": {"login": "bob"}, "body": "hello"},
        ])
    thread = _adapter(handler).get_thread("o/r", 1)
    assert thread[0].author == "bob"
    assert thread[0].id == "1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_github_write.py -v`
Expected: FAIL — the stubs raise `NotImplementedError`.

- [ ] **Step 3: Write minimal implementation**

In `app/git/github.py`, replace the five stub methods with:
```python
    def post_comment(self, repo, pr_number, body) -> str:
        r = self._post(f"/repos/{repo}/issues/{pr_number}/comments", {"body": body})
        return str(r["id"])

    def post_inline_comment(self, repo, pr_number, path, line, body, side: Side) -> str:
        commit_id = self.get_pr_meta(repo, pr_number).head_sha
        r = self._post(f"/repos/{repo}/pulls/{pr_number}/comments", {
            "body": body, "path": path, "line": line,
            "side": side.name.upper(), "commit_id": commit_id,
        })
        return str(r["id"])

    def set_review_verdict(self, repo, pr_number, verdict: Verdict, body) -> None:
        self._post(f"/repos/{repo}/pulls/{pr_number}/reviews",
                   {"event": _VERDICT_EVENT[verdict], "body": body})

    def get_thread(self, repo, pr_number) -> list[Comment]:
        rows = self._get(f"/repos/{repo}/issues/{pr_number}/comments")
        return [Comment(id=str(c["id"]), author=c.get("user", {}).get("login", ""),
                        body=c.get("body", "")) for c in rows]

    def reply(self, repo, pr_number, in_reply_to, body) -> str:
        r = self._post(f"/repos/{repo}/issues/{pr_number}/comments", {"body": body})
        return str(r["id"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_github_write.py tests/test_github_read.py -v`
Expected: PASS (read tests still green, 4 write tests pass)

- [ ] **Step 5: Commit**

```bash
git add app/git/github.py tests/test_github_write.py
git commit -m "feat: GitHubAdapter write methods (comments, reviews, thread)"
```

---

### Task 4: Git adapter factory

**Files:**
- Create: `app/git/factory.py`
- Test: `tests/test_git_factory.py`

**Interfaces:**
- Consumes: `RepoConfig` from `app.config`, `Platform`, `GitHubAdapter`.
- Produces:
  - `build_git_adapter(repo_config, transport=None) -> GitPlatformAdapter` — for `Platform.github` returns `GitHubAdapter(repo_config.full_name, repo_config.token, transport=transport)`; for `bitbucket`/`gitlab` raises `NotImplementedError` with a clear "not yet implemented" message; unknown → `ValueError`.

- [ ] **Step 1: Write the failing test**

`tests/test_git_factory.py`:
```python
import pytest
from app.config import RepoConfig
from app.git.factory import build_git_adapter
from app.git.github import GitHubAdapter
from app.models import Platform


def test_builds_github_adapter():
    rc = RepoConfig(platform=Platform.github, full_name="o/r", token="t")
    a = build_git_adapter(rc)
    assert isinstance(a, GitHubAdapter)
    assert a.repo == "o/r"


def test_bitbucket_not_implemented():
    rc = RepoConfig(platform=Platform.bitbucket, full_name="o/r", token="t")
    with pytest.raises(NotImplementedError):
        build_git_adapter(rc)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_git_factory.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.git.factory'`

- [ ] **Step 3: Write minimal implementation**

`app/git/factory.py`:
```python
from __future__ import annotations

from app.config import RepoConfig
from app.git.base import GitPlatformAdapter
from app.git.github import GitHubAdapter
from app.models import Platform


def build_git_adapter(repo_config: RepoConfig, transport=None) -> GitPlatformAdapter:
    if repo_config.platform == Platform.github:
        return GitHubAdapter(repo_config.full_name, repo_config.token,
                             transport=transport)
    if repo_config.platform in (Platform.bitbucket, Platform.gitlab):
        raise NotImplementedError(
            f"{repo_config.platform.value} adapter not yet implemented")
    raise ValueError(f"Unknown platform: {repo_config.platform}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_git_factory.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/git/factory.py tests/test_git_factory.py
git commit -m "feat: git adapter factory (github)"
```

---

### Task 5: Config — LLMConfig gains api_key and base_url

**Files:**
- Modify: `app/config.py` (`LLMConfig`)
- Test: `tests/test_config.py` (add one case)

**Interfaces:**
- Consumes: existing config.
- Produces: `LLMConfig` gains `api_key: str = ""` and `base_url: str | None = None` (both optional; existing configs keep working). No other changes.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:
```python
def test_llm_config_api_key_and_base_url(tmp_path):
    path = _write(tmp_path, """
llm:
  provider: openai
  model: gpt-x
  api_key: ${OAI}
  base_url: http://localhost:11434/v1
store: {url: 'sqlite:///:memory:'}
defaults: {tasks: [code_review]}
repos: []
""")
    s = load_settings(path, env={"OAI": "sk-test"})
    assert s.llm.api_key == "sk-test"
    assert s.llm.base_url == "http://localhost:11434/v1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py::test_llm_config_api_key_and_base_url -v`
Expected: FAIL — `LLMConfig` has no `api_key`/`base_url` (pydantic ignores or errors; assertion fails).

- [ ] **Step 3: Write minimal implementation**

In `app/config.py`, update `LLMConfig`:
```python
class LLMConfig(BaseModel):
    provider: str = "fake"
    model: str = "fake"
    api_key: str = ""
    base_url: str | None = None
    max_tokens_per_pr: int = 40000
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (existing 3 + new 1 = 4)

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat: LLMConfig api_key and base_url"
```

---

### Task 6: Claude LLM adapter

**Files:**
- Create: `app/llm/http_llm.py`
- Create: `app/llm/claude.py`
- Test: `tests/test_claude.py`

**Interfaces:**
- Consumes: `LLMAdapter`, `Message`, `LLMResponse`, `build_client`, `raise_for_status`.
- Produces:
  - `app/llm/http_llm.py`: `post_json(client, path, payload) -> dict` — POST + `raise_for_status` + `.json()`.
  - `class ClaudeAdapter(LLMAdapter)` = `ClaudeAdapter(api_key, model, transport=None, api_base="https://api.anthropic.com")`. `complete` POSTs `/v1/messages` with headers `x-api-key`, `anthropic-version: 2023-06-01`, body `{model, max_tokens, system, messages:[{role, content}]}`; response text = concatenation of `content[].text` where `type=="text"`; `usage_tokens = usage.input_tokens + usage.output_tokens`. `count_tokens = len(text.split())`.

- [ ] **Step 1: Write the failing test**

`tests/test_claude.py`:
```python
import httpx
from app.llm.claude import ClaudeAdapter
from app.llm.base import Message


def test_complete_maps_messages_and_response():
    seen = {}
    def handler(request):
        import json
        assert request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == "sk"
        assert request.headers["anthropic-version"] == "2023-06-01"
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={
            "content": [{"type": "text", "text": "Looks good."}],
            "usage": {"input_tokens": 10, "output_tokens": 3},
        })
    a = ClaudeAdapter("sk", "claude-sonnet-5", transport=httpx.MockTransport(handler))
    r = a.complete("be brief", [Message(role="user", content="review this")], max_tokens=100)
    assert r.text == "Looks good."
    assert r.usage_tokens == 13
    assert seen["system"] == "be brief"
    assert seen["messages"][0] == {"role": "user", "content": "review this"}
    assert seen["max_tokens"] == 100


def test_count_tokens():
    a = ClaudeAdapter("sk", "m", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    assert a.count_tokens("a b c") == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_claude.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.llm.claude'`

- [ ] **Step 3: Write minimal implementation**

`app/llm/http_llm.py`:
```python
from __future__ import annotations

from app.http import raise_for_status


def post_json(client, path: str, payload: dict) -> dict:
    resp = client.post(path, json=payload)
    raise_for_status(resp)
    return resp.json()
```

`app/llm/claude.py`:
```python
from __future__ import annotations

from app.http import build_client
from app.llm.base import LLMAdapter, Message, LLMResponse
from app.llm.http_llm import post_json


class ClaudeAdapter(LLMAdapter):
    def __init__(self, api_key: str, model: str, transport=None,
                 api_base: str = "https://api.anthropic.com"):
        self.model = model
        self._client = build_client(
            api_base,
            {"x-api-key": api_key, "anthropic-version": "2023-06-01",
             "content-type": "application/json"},
            transport=transport,
        )

    def complete(self, system, messages, max_tokens) -> LLMResponse:
        data = post_json(self._client, "/v1/messages", {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        })
        text = "".join(b.get("text", "") for b in data.get("content", [])
                       if b.get("type") == "text")
        usage = data.get("usage", {})
        tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        return LLMResponse(text=text, usage_tokens=tokens)

    def count_tokens(self, text: str) -> int:
        return len(text.split())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_claude.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/llm/http_llm.py app/llm/claude.py tests/test_claude.py
git commit -m "feat: Claude LLM adapter over httpx"
```

---

### Task 7: OpenAI + Local LLM adapters

**Files:**
- Create: `app/llm/openai.py`
- Create: `app/llm/local.py`
- Test: `tests/test_openai_local.py`

**Interfaces:**
- Consumes: `LLMAdapter`, `Message`, `LLMResponse`, `build_client`, `post_json`.
- Produces:
  - `class OpenAIAdapter(LLMAdapter)` = `OpenAIAdapter(api_key, model, base_url="https://api.openai.com/v1", transport=None)`. `complete` POSTs `/chat/completions` (relative to `base_url`) with `Authorization: Bearer <api_key>`, body `{model, max_tokens, messages: [{role:"system", content:system}, *user/assistant messages]}`; text = `choices[0].message.content`; `usage_tokens = usage.total_tokens`. `count_tokens = len(text.split())`.
  - `class LocalAdapter(OpenAIAdapter)` = `LocalAdapter(model, base_url, api_key="", transport=None)` — an OpenAI-compatible local endpoint (e.g. Ollama at `http://localhost:11434/v1`); just calls `super().__init__` with the given base_url and (possibly empty) key.

- [ ] **Step 1: Write the failing test**

`tests/test_openai_local.py`:
```python
import httpx
from app.llm.openai import OpenAIAdapter
from app.llm.local import LocalAdapter
from app.llm.base import Message


def _resp():
    return {"choices": [{"message": {"content": "ok"}}],
            "usage": {"total_tokens": 42}}


def test_openai_complete_maps():
    seen = {}
    def handler(request):
        import json
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer sk"
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=_resp())
    a = OpenAIAdapter("sk", "gpt-x", transport=httpx.MockTransport(handler))
    r = a.complete("sys", [Message(role="user", content="hi")], max_tokens=50)
    assert r.text == "ok"
    assert r.usage_tokens == 42
    assert seen["messages"][0] == {"role": "system", "content": "sys"}
    assert seen["messages"][1] == {"role": "user", "content": "hi"}


def test_local_uses_given_base_url():
    hit = {}
    def handler(request):
        hit["host"] = request.url.host
        hit["path"] = request.url.path
        return httpx.Response(200, json=_resp())
    a = LocalAdapter("llama", "http://localhost:11434/v1",
                     transport=httpx.MockTransport(handler))
    r = a.complete("s", [Message(role="user", content="x")], max_tokens=10)
    assert r.text == "ok"
    assert hit["host"] == "localhost"
    assert hit["path"] == "/v1/chat/completions"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_openai_local.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.llm.openai'`

- [ ] **Step 3: Write minimal implementation**

`app/llm/openai.py`:
```python
from __future__ import annotations

from app.http import build_client
from app.llm.base import LLMAdapter, Message, LLMResponse
from app.llm.http_llm import post_json


class OpenAIAdapter(LLMAdapter):
    def __init__(self, api_key: str, model: str,
                 base_url: str = "https://api.openai.com/v1", transport=None):
        self.model = model
        self._client = build_client(
            base_url,
            {"Authorization": f"Bearer {api_key}",
             "content-type": "application/json"},
            transport=transport,
        )

    def complete(self, system, messages, max_tokens) -> LLMResponse:
        payload_messages = [{"role": "system", "content": system}]
        payload_messages += [{"role": m.role, "content": m.content} for m in messages]
        data = post_json(self._client, "/chat/completions", {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": payload_messages,
        })
        text = data["choices"][0]["message"]["content"]
        tokens = data.get("usage", {}).get("total_tokens", 0)
        return LLMResponse(text=text, usage_tokens=tokens)

    def count_tokens(self, text: str) -> int:
        return len(text.split())
```

`app/llm/local.py`:
```python
from __future__ import annotations

from app.llm.openai import OpenAIAdapter


class LocalAdapter(OpenAIAdapter):
    def __init__(self, model: str, base_url: str, api_key: str = "", transport=None):
        super().__init__(api_key=api_key, model=model, base_url=base_url,
                         transport=transport)
```

Note: `build_client` sets `base_url="http://localhost:11434/v1"`, and the POST path is `/chat/completions`; httpx joins these to `/v1/chat/completions`. Ensure `base_url` has no trailing slash and the path is `chat/completions` vs `/chat/completions` consistent with the test — the test expects final path `/v1/chat/completions`, so pass base_url ending in `/v1` and call `post_json(self._client, "/chat/completions", ...)`. httpx resolves a leading-slash path against the base_url's host, DROPPING the base path. To preserve `/v1`, the client must be built with the path-inclusive base_url AND the request path must be relative WITHOUT a leading slash. Use `post_json(self._client, "chat/completions", ...)` and build the client with `base_url` ending in `/v1/`. Update accordingly:
- In `OpenAIAdapter.__init__`, normalize: `base_url = base_url.rstrip("/") + "/"`.
- Call `post_json(self._client, "chat/completions", ...)`.
- Apply the same rule in `ClaudeAdapter` (Task 6): build client with `api_base` and call path `"/v1/messages"` — since Claude's `api_base` has no path, a leading-slash path is correct there. Only the OpenAI `/v1` base needs the trailing-slash + relative-path treatment.

Implementer: verify the exact resolved path with the test's assertion (`/v1/chat/completions`); adjust trailing slash / leading slash until the MockTransport sees that path. This is the one fiddly bit in this task.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_openai_local.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/llm/openai.py app/llm/local.py tests/test_openai_local.py
git commit -m "feat: OpenAI and local LLM adapters"
```

---

### Task 8: LLM adapter factory

**Files:**
- Create: `app/llm/factory.py`
- Test: `tests/test_llm_factory.py`

**Interfaces:**
- Consumes: `LLMConfig`, `FakeLLMAdapter`, `ClaudeAdapter`, `OpenAIAdapter`, `LocalAdapter`.
- Produces:
  - `build_llm_adapter(cfg: LLMConfig, transport=None) -> LLMAdapter`:
    - `"fake"` → `FakeLLMAdapter(responses=[""])`
    - `"claude"` → `ClaudeAdapter(cfg.api_key, cfg.model, transport=transport)`
    - `"openai"` → `OpenAIAdapter(cfg.api_key, cfg.model, base_url=cfg.base_url or "https://api.openai.com/v1", transport=transport)`
    - `"local"` → `LocalAdapter(cfg.model, cfg.base_url or "http://localhost:11434/v1", api_key=cfg.api_key, transport=transport)`
    - unknown → `ValueError`.

- [ ] **Step 1: Write the failing test**

`tests/test_llm_factory.py`:
```python
import pytest
from app.config import LLMConfig
from app.llm.factory import build_llm_adapter
from app.llm.claude import ClaudeAdapter
from app.llm.openai import OpenAIAdapter
from app.llm.local import LocalAdapter
from app.llm.fake import FakeLLMAdapter


def test_fake():
    assert isinstance(build_llm_adapter(LLMConfig(provider="fake")), FakeLLMAdapter)


def test_claude():
    a = build_llm_adapter(LLMConfig(provider="claude", model="m", api_key="k"))
    assert isinstance(a, ClaudeAdapter)


def test_openai():
    a = build_llm_adapter(LLMConfig(provider="openai", model="m", api_key="k"))
    assert isinstance(a, OpenAIAdapter) and not isinstance(a, LocalAdapter)


def test_local():
    a = build_llm_adapter(LLMConfig(provider="local", model="m",
                                    base_url="http://localhost:11434/v1"))
    assert isinstance(a, LocalAdapter)


def test_unknown_raises():
    with pytest.raises(ValueError):
        build_llm_adapter(LLMConfig(provider="mystery"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm_factory.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.llm.factory'`

- [ ] **Step 3: Write minimal implementation**

`app/llm/factory.py`:
```python
from __future__ import annotations

from app.config import LLMConfig
from app.llm.base import LLMAdapter
from app.llm.fake import FakeLLMAdapter
from app.llm.claude import ClaudeAdapter
from app.llm.openai import OpenAIAdapter
from app.llm.local import LocalAdapter


def build_llm_adapter(cfg: LLMConfig, transport=None) -> LLMAdapter:
    p = cfg.provider
    if p == "fake":
        return FakeLLMAdapter(responses=[""])
    if p == "claude":
        return ClaudeAdapter(cfg.api_key, cfg.model, transport=transport)
    if p == "openai":
        return OpenAIAdapter(cfg.api_key, cfg.model,
                             base_url=cfg.base_url or "https://api.openai.com/v1",
                             transport=transport)
    if p == "local":
        return LocalAdapter(cfg.model, cfg.base_url or "http://localhost:11434/v1",
                            api_key=cfg.api_key, transport=transport)
    raise ValueError(f"Unknown LLM provider: {p}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_llm_factory.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add app/llm/factory.py tests/test_llm_factory.py
git commit -m "feat: llm adapter factory"
```

---

### Task 9: End-to-end integration + example config + README

**Files:**
- Create: `tests/test_integration_real.py`
- Create: `config.example.yaml`
- Modify: `README.md`
- Test: the integration test + full suite

**Interfaces:**
- Consumes: `Reviewer`, `GitHubAdapter`, `ClaudeAdapter` (both via MockTransport), factories.
- Produces: a test proving the real adapters drive the reviewer end-to-end offline; a documented example config.

- [ ] **Step 1: Write the failing test**

`tests/test_integration_real.py`:
```python
import httpx
from app.reviewer import Reviewer
from app.git.github import GitHubAdapter
from app.llm.claude import ClaudeAdapter


def test_reviewer_runs_with_real_adapters_over_mock_http():
    def gh(request):
        p = request.url.path
        if p == "/repos/o/r/pulls/1":
            return httpx.Response(200, json={
                "title": "t", "body": "", "user": {"login": "a"},
                "base": {"sha": "b"}, "head": {"sha": "H"}, "labels": [],
            })
        if p == "/repos/o/r/commits/H/status":
            return httpx.Response(200, json={"state": "success"})
        if p == "/repos/o/r/pulls/1/files":
            return httpx.Response(200, json=[
                {"filename": "app.py", "patch": "@@ +x", "additions": 1,
                 "deletions": 0, "status": "modified"}])
        if p == "/repos/o/r/issues/1/comments":
            return httpx.Response(201, json={"id": 100})
        return httpx.Response(404, text=p)

    def llm(request):
        return httpx.Response(200, json={
            "content": [{"type": "text", "text": "This PR edits app.py."}],
            "usage": {"input_tokens": 5, "output_tokens": 5},
        })

    git = GitHubAdapter("o/r", "tok", transport=httpx.MockTransport(gh))
    claude = ClaudeAdapter("sk", "claude-sonnet-5", transport=httpx.MockTransport(llm))
    results = Reviewer(git, claude).review("o/r", 1, ["summarize"])
    assert [r.name for r in results] == ["summarize"]
    assert results[0].posted == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_integration_real.py -v`
Expected: FAIL — until you confirm; if the adapters are correct it may already pass. If it fails, fix the adapter, not the test.

- [ ] **Step 3: Add example config + README section**

`config.example.yaml`:
```yaml
llm:
  provider: claude          # claude | openai | local | fake
  model: claude-sonnet-5
  api_key: ${LLM_API_KEY}
  base_url: null            # set for local, e.g. http://localhost:11434/v1
  max_tokens_per_pr: 40000
store:
  url: sqlite:///data/agent.db
defaults:
  tasks: [code_review, summarize]
repos:
  - platform: github
    full_name: owner/repo
    token: ${GITHUB_TOKEN}
    tasks: null
```

Append to `README.md`:
```markdown
## Real adapters (slice 2)
GitHub platform adapter and Claude/OpenAI/local LLM adapters are implemented
over httpx and selected via config (see `config.example.yaml`). All adapter
tests run offline using `httpx.MockTransport` — no live API calls.

    cp config.example.yaml config.yaml   # then set env vars

Providers: `claude` (Anthropic /v1/messages), `openai` (/v1/chat/completions),
`local` (OpenAI-compatible endpoint like Ollama), `fake` (offline default).
```

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: PASS — all Plan 1 tests (30) + all Plan 2 tests, zero network, pristine output.

- [ ] **Step 5: Commit**

```bash
git add tests/test_integration_real.py config.example.yaml README.md
git commit -m "feat: end-to-end integration with real adapters + example config"
```

---

## Self-Review

**Spec coverage (this slice = spec milestones 4,5,6-partial):**
- Real GitHub adapter mapping API→neutral types (§4.1, milestone 6) → Tasks 2,3. ✓
- Git factory (§4) → Task 4. ✓
- Claude adapter (§4.2, milestone 7) → Task 6. ✓
- OpenAI adapter → Task 7. ✓
- Local (OpenAI-compatible) adapter → Task 7. ✓
- LLM factory + config selection (§7) → Tasks 5,8. ✓
- Offline contract testing via MockTransport (§10 test strategy) → all tasks. ✓
- End-to-end with real adapters → Task 9. ✓
- Deferred to later slices: `.pr-agent.yaml` fetch, list_open_prs / add_labels / assign_reviewers (needed by poller & triage), Bitbucket/GitLab, redaction, ingress/poller, rules, remaining 5 tasks, UI. Interface unchanged so these layer on cleanly.

**Placeholder scan:** No TBD/TODO. Two deliberate implementer notes flagged inline: (a) the fullwidth `）` typo in Task 2 get_diff to fix on transcription; (b) the httpx base_url/leading-slash path resolution in Task 7 — both call out the exact correct end state (assertion `/v1/chat/completions`). These are guidance, not placeholders.

**Type consistency:** `GitHubAdapter(repo, token, transport, api_base)` used consistently in Tasks 2,3,4,9. `_VERDICT_EVENT` keyed by `Verdict` enum (Task 2 defines, Task 3 uses). `build_client`/`raise_for_status`/`post_json` signatures stable across Tasks 1,2,6,7. `LLMConfig.api_key`/`base_url` (Task 5) consumed by factory (Task 8). Factory provider strings (`fake/claude/openai/local`) match `LLMConfig.provider`. `Side.name.upper()` → "RIGHT"/"LEFT" matches GitHub's `side` field.
