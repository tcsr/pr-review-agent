# PR Review Agent — Verdict, Suggest-Fixes, Triage & Redaction Plan (Plan 5 of N)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three more review tasks — `verdict` (sets approve/request_changes, enforcing block-gates), `suggest_fixes` (inline GitHub suggestion blocks), and `triage` (size/type labels) — plus a redaction pass that strips secrets from diffs before any diff text reaches an LLM.

**Architecture:** The three tasks slot into the existing `Task`/`ReviewContext` machinery (same `run(..., context=None)` signature, registered in the reviewer). `verdict` reuses `evaluate_gates`: a failed `block` gate forces `request_changes` without calling the LLM; otherwise it asks the LLM for a verdict. `triage` needs two new `GitPlatformAdapter` methods (`add_labels`, `assign_reviewers`) added across the interface, GitHub, and fake. Redaction is a pure function the reviewer applies to the fetched diff once, before building the context — so every LLM-facing task sees scrubbed patches while gates still see real paths/counts (redaction only rewrites patch text).

**Tech Stack:** Python 3.11+ (stdlib `re`, `json`), httpx (existing). No new dependencies.

## Global Constraints

- Python 3.11+ (`from __future__ import annotations`).
- **No network in tests.** LLM tasks use `FakeLLMAdapter`; GitHub label/reviewer calls tested via `httpx.MockTransport`.
- Redaction runs in the reviewer before tasks; it rewrites `FileChange.patch` only — file paths, counts, additions/deletions are preserved so gates and detection are unaffected.
- New tasks follow the established `Task.run(self, git, llm, repo, pr_number, meta, diff, context=None) -> TaskResult` signature and register in `TASK_REGISTRY` + `_PRIORITY`.
- `verdict`: a failed `block` gate forces `Verdict.request_changes` with the failing gates listed, and the LLM is NOT called in that case. With no blocking failures, the LLM decides (approve/request_changes/comment); malformed LLM output defaults to `Verdict.comment`.
- The `GitPlatformAdapter` interface gains `add_labels` and `assign_reviewers`; both concretes (GitHub, fake) must implement them.
- Secrets are never logged; redaction replaces matched secrets with `***REDACTED***`.
- Every code change lands via TDD: failing test first, minimal impl, green, commit.

---

## File Structure

```
app/
  redact.py                 # redact_text(str) -> str; redact_diff(Diff) -> Diff
  reviewer.py               # MODIFY: redact diff before building context
  git/base.py               # MODIFY: add add_labels, assign_reviewers (abstract)
  git/github.py             # MODIFY: implement add_labels, assign_reviewers
  git/fake.py               # MODIFY: implement add_labels, assign_reviewers (record)
  tasks/
    verdict.py              # VerdictTask
    suggest_fixes.py        # SuggestFixesTask
    triage.py               # TriageTask
  reviewer.py               # MODIFY: register verdict/suggest_fixes/triage
tests/
  test_redact.py
  test_verdict.py
  test_suggest_fixes.py
  test_labels_reviewers.py
  test_triage.py
```

---

### Task 1: Secret redaction + reviewer wiring

**Files:**
- Create: `app/redact.py`
- Modify: `app/reviewer.py` (redact the diff before building context)
- Test: `tests/test_redact.py`

**Interfaces:**
- Consumes: `Diff`, `FileChange`.
- Produces:
  - `redact_text(text: str) -> str` — replaces matches of known secret patterns with `***REDACTED***`. Patterns: OpenAI-style `sk-[A-Za-z0-9]{20,}`, GitHub `ghp_[A-Za-z0-9]{36}`, AWS `AKIA[0-9A-Z]{16}`, and generic `key/secret/token/password = value` assignments (`(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[A-Za-z0-9._\-]{8,}` → keep the label, redact the value).
  - `redact_diff(diff: Diff) -> Diff` — returns a NEW `Diff` with each `FileChange` copied but `patch` passed through `redact_text`; path/additions/deletions/status unchanged.
  - Reviewer applies `redact_diff` to the fetched diff before building `ReviewContext` and passing the diff to tasks.

- [ ] **Step 1: Write the failing test**

`tests/test_redact.py`:
```python
from app.redact import redact_text, redact_diff
from app.models import Diff, FileChange


def test_redacts_openai_key():
    out = redact_text("token = sk-abcdefghijklmnopqrstuvwxyz012345")
    assert "sk-abcdefghijk" not in out
    assert "REDACTED" in out


def test_redacts_github_and_aws():
    assert "REDACTED" in redact_text("ghp_" + "a" * 36)
    assert "REDACTED" in redact_text("AKIA" + "ABCDEFGHIJKLMNOP")


def test_redacts_generic_assignment():
    out = redact_text('API_KEY = "hunter2secretvalue"')
    assert "hunter2secretvalue" not in out
    assert "REDACTED" in out


def test_leaves_ordinary_code_untouched():
    code = "def add(a, b):\n    return a + b"
    assert redact_text(code) == code


def test_redact_diff_preserves_metadata_and_scrubs_patch():
    d = Diff(files=[FileChange(path="a.py", patch="key = sk-abcdefghijklmnopqrstuvwxyz012345",
                              additions=1, deletions=0, status="modified")])
    out = redact_diff(d)
    assert out.files[0].path == "a.py"
    assert out.files[0].additions == 1
    assert "REDACTED" in out.files[0].patch
    # original untouched
    assert "sk-abcdefghijk" in d.files[0].patch
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_redact.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.redact'`

- [ ] **Step 3: Write minimal implementation**

`app/redact.py`:
```python
from __future__ import annotations

import re

from app.models import Diff, FileChange

_REDACTED = "***REDACTED***"

_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
]
_ASSIGN = re.compile(
    r"(?i)(api[_-]?key|secret|token|password)(\s*[:=]\s*)['\"]?[A-Za-z0-9._\-]{8,}['\"]?"
)


def redact_text(text: str) -> str:
    for pat in _PATTERNS:
        text = pat.sub(_REDACTED, text)
    text = _ASSIGN.sub(lambda m: f"{m.group(1)}{m.group(2)}{_REDACTED}", text)
    return text


def redact_diff(diff: Diff) -> Diff:
    return Diff(files=[
        FileChange(path=f.path, patch=redact_text(f.patch), additions=f.additions,
                   deletions=f.deletions, status=f.status)
        for f in diff.files
    ])
```

In `app/reviewer.py`, import and apply before building context:
```python
from app.redact import redact_diff
...
        meta = self.git.get_pr_meta(repo, pr_number)
        diff = redact_diff(self.git.get_diff(repo, pr_number))
        stacks = detect_stacks(diff)
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_redact.py tests/test_reviewer.py -v`
Expected: PASS — redaction tests pass; existing reviewer tests still green (sample_diff has no secrets → redaction is a no-op).

- [ ] **Step 5: Commit**

```bash
git add app/redact.py app/reviewer.py tests/test_redact.py
git commit -m "feat: secret redaction of diffs before LLM"
```

---

### Task 2: Verdict task

**Files:**
- Create: `app/tasks/verdict.py`
- Modify: `app/reviewer.py` (register `verdict`)
- Test: `tests/test_verdict.py`

**Interfaces:**
- Consumes: `Task`, `TaskResult`, `evaluate_gates`, `Verdict`, `Message`, `_render_diff`.
- Produces:
  - `class VerdictTask(Task)`: `name = "verdict"`.
    - Evaluate gates from `context.gates` (empty if no context). If any result has `not passed and severity == "block"`: call `git.set_review_verdict(repo, pr, Verdict.request_changes, body)` where body lists the failing gates; return `TaskResult("verdict", 1)` — do NOT call the LLM.
    - Otherwise, prompt the LLM for a JSON `{"verdict": "approve|request_changes|comment", "reason": str}`; map to `Verdict` (unknown/malformed → `Verdict.comment`); call `set_review_verdict`; return `TaskResult("verdict", 1)`.
  - Register `TASK_REGISTRY["verdict"] = VerdictTask` (priority already `9`).

- [ ] **Step 1: Write the failing test**

`tests/test_verdict.py`:
```python
import json
from app.tasks.verdict import VerdictTask
from app.review_context import ReviewContext
from app.config import GateConfig
from app.models import Verdict
from app.git.fake import FakeGitAdapter
from app.llm.fake import FakeLLMAdapter
from tests.fixtures import sample_meta, sample_diff


def _git(**over):
    return FakeGitAdapter(seed={("o/r", 1): (sample_meta(**over), sample_diff())})


def test_blocking_gate_forces_request_changes_without_llm():
    git = _git(ci_passed=False)
    llm = FakeLLMAdapter(responder=lambda s, m: (_ for _ in ()).throw(AssertionError("LLM must not be called")))
    ctx = ReviewContext(gates={"ci_must_pass": GateConfig(severity="block")})
    res = VerdictTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1),
                            git.get_diff("o/r", 1), context=ctx)
    assert res.posted == 1
    assert git.verdicts[0][0] == Verdict.request_changes


def test_llm_verdict_used_when_no_blocking_failures():
    git = _git()
    llm = FakeLLMAdapter(responses=[json.dumps({"verdict": "approve", "reason": "LGTM"})])
    res = VerdictTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1),
                            git.get_diff("o/r", 1), context=ReviewContext())
    assert git.verdicts[0][0] == Verdict.approve


def test_malformed_llm_defaults_to_comment():
    git = _git()
    llm = FakeLLMAdapter(responses=["not json"])
    VerdictTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1),
                      git.get_diff("o/r", 1), context=ReviewContext())
    assert git.verdicts[0][0] == Verdict.comment
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_verdict.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.tasks.verdict'`

- [ ] **Step 3: Write minimal implementation**

`app/tasks/verdict.py`:
```python
from __future__ import annotations

import json

from app.llm.base import Message
from app.models import Verdict
from app.rules.gates import evaluate_gates
from app.tasks.base import Task, TaskResult
from app.tasks.code_review import _render_diff

_SYSTEM = (
    'You are a PR gatekeeper. Respond ONLY with JSON '
    '{"verdict": "approve|request_changes|comment", "reason": str}.'
)
_MAP = {
    "approve": Verdict.approve,
    "request_changes": Verdict.request_changes,
    "comment": Verdict.comment,
}


class VerdictTask(Task):
    name = "verdict"

    def run(self, git, llm, repo, pr_number, meta, diff, context=None) -> TaskResult:
        gates = context.gates if context else {}
        results = evaluate_gates(meta, diff, gates)
        blocking = [r for r in results if not r.passed and r.severity == "block"]
        if blocking:
            body = "Blocking gate failures:\n" + "\n".join(
                f"- {r.name}: {r.message}" for r in blocking)
            git.set_review_verdict(repo, pr_number, Verdict.request_changes, body)
            return TaskResult(self.name, 1)

        prompt = f"PR title: {meta.title}\n\nDiff:\n{_render_diff(diff)}\n\nGive your verdict."
        resp = llm.complete(_SYSTEM, [Message(role="user", content=prompt)], max_tokens=500)
        verdict, reason = Verdict.comment, ""
        try:
            data = json.loads(resp.text)
            verdict = _MAP.get(data.get("verdict"), Verdict.comment)
            reason = data.get("reason", "")
        except (json.JSONDecodeError, AttributeError):
            pass
        git.set_review_verdict(repo, pr_number, verdict, reason)
        return TaskResult(self.name, 1)
```

In `app/reviewer.py`, add to imports and registry:
```python
from app.tasks.verdict import VerdictTask
...
    "verdict": VerdictTask,
```
(`_PRIORITY` already has `"verdict": 9`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_verdict.py tests/test_reviewer.py -v`
Expected: PASS (3 verdict + reviewer green)

- [ ] **Step 5: Commit**

```bash
git add app/tasks/verdict.py app/reviewer.py tests/test_verdict.py
git commit -m "feat: verdict task with block-gate enforcement"
```

---

### Task 3: Suggest-fixes task

**Files:**
- Create: `app/tasks/suggest_fixes.py`
- Modify: `app/reviewer.py` (register `suggest_fixes`, priority `3`)
- Test: `tests/test_suggest_fixes.py`

**Interfaces:**
- Consumes: `Task`, `TaskResult`, `Message`, `Side`, `_render_diff`.
- Produces:
  - `class SuggestFixesTask(Task)`: `name = "suggest_fixes"`. Prompts the LLM for a JSON list of `{path, line, comment, suggestion}`; for each, posts an inline comment whose body is `f"{comment}\n\n```suggestion\n{suggestion}\n```"` via `git.post_inline_comment(..., Side.right)`; counts posted. Malformed JSON or non-list → posts nothing, returns `TaskResult("suggest_fixes", 0)`. A finding missing a required key is skipped (not fatal).
  - Register `TASK_REGISTRY["suggest_fixes"] = SuggestFixesTask`; `_PRIORITY["suggest_fixes"] = 3`.

- [ ] **Step 1: Write the failing test**

`tests/test_suggest_fixes.py`:
```python
import json
from app.tasks.suggest_fixes import SuggestFixesTask
from app.git.fake import FakeGitAdapter
from app.llm.fake import FakeLLMAdapter
from tests.fixtures import sample_meta, sample_diff


def _git():
    return FakeGitAdapter(seed={("o/r", 1): (sample_meta(), sample_diff())})


def test_posts_suggestion_block():
    git = _git()
    findings = json.dumps([{"path": "src/app.py", "line": 1,
                            "comment": "Rename for clarity.", "suggestion": "new_value = 1"}])
    llm = FakeLLMAdapter(responses=[findings])
    res = SuggestFixesTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1),
                                 git.get_diff("o/r", 1))
    assert res.posted == 1
    body = git.inline_comments[0].body
    assert "```suggestion" in body
    assert "new_value = 1" in body


def test_malformed_posts_nothing():
    git = _git()
    llm = FakeLLMAdapter(responses=["not json"])
    res = SuggestFixesTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1),
                                 git.get_diff("o/r", 1))
    assert res.posted == 0


def test_finding_missing_key_skipped():
    git = _git()
    llm = FakeLLMAdapter(responses=[json.dumps([{"path": "a", "line": 1}])])  # no suggestion
    res = SuggestFixesTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1),
                                 git.get_diff("o/r", 1))
    assert res.posted == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_suggest_fixes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.tasks.suggest_fixes'`

- [ ] **Step 3: Write minimal implementation**

`app/tasks/suggest_fixes.py`:
```python
from __future__ import annotations

import json

from app.llm.base import Message
from app.models import Side
from app.tasks.base import Task, TaskResult
from app.tasks.code_review import _render_diff

_SYSTEM = (
    "You are a code reviewer proposing concrete fixes. Return ONLY a JSON array "
    'of {"path": str, "line": int, "comment": str, "suggestion": str} where '
    "suggestion is the replacement code for that line. No prose."
)


class SuggestFixesTask(Task):
    name = "suggest_fixes"

    def run(self, git, llm, repo, pr_number, meta, diff, context=None) -> TaskResult:
        prompt = f"PR title: {meta.title}\n\nDiff:\n{_render_diff(diff)}\n\nPropose fixes as JSON."
        resp = llm.complete(_SYSTEM, [Message(role="user", content=prompt)], max_tokens=2000)
        try:
            findings = json.loads(resp.text)
            assert isinstance(findings, list)
        except (json.JSONDecodeError, AssertionError):
            return TaskResult(self.name, 0)
        posted = 0
        for f in findings:
            try:
                body = f"{f['comment']}\n\n```suggestion\n{f['suggestion']}\n```"
                git.post_inline_comment(repo, pr_number, f["path"], f["line"], body, Side.right)
                posted += 1
            except (KeyError, TypeError):
                continue
        return TaskResult(self.name, posted)
```

In `app/reviewer.py`, register:
```python
from app.tasks.suggest_fixes import SuggestFixesTask
...
    "suggest_fixes": SuggestFixesTask,
...
_PRIORITY = {"triage": 1, "code_review": 0, "suggest_fixes": 3, "summarize": 5,
             "compliance": 7, "verdict": 9}
```
(Adjust the existing `_PRIORITY` dict to include `suggest_fixes: 3`; `triage` added in Task 5.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_suggest_fixes.py tests/test_reviewer.py -v`
Expected: PASS (3 + reviewer green)

- [ ] **Step 5: Commit**

```bash
git add app/tasks/suggest_fixes.py app/reviewer.py tests/test_suggest_fixes.py
git commit -m "feat: suggest_fixes task with GitHub suggestion blocks"
```

---

### Task 4: add_labels and assign_reviewers across the adapter interface

**Files:**
- Modify: `app/git/base.py` (two new abstract methods)
- Modify: `app/git/github.py` (implement both)
- Modify: `app/git/fake.py` (implement both, record)
- Test: `tests/test_labels_reviewers.py`

**Interfaces:**
- Produces:
  - `GitPlatformAdapter.add_labels(repo, pr_number, labels: list[str]) -> None` (abstract).
  - `GitPlatformAdapter.assign_reviewers(repo, pr_number, reviewers: list[str]) -> None` (abstract).
  - `GitHubAdapter.add_labels` — POST `/repos/{repo}/issues/{pr_number}/labels` `{"labels": labels}`.
  - `GitHubAdapter.assign_reviewers` — POST `/repos/{repo}/pulls/{pr_number}/requested_reviewers` `{"reviewers": reviewers}`.
  - `FakeGitAdapter` — new public lists `self.labels: list[str]` and `self.reviewers: list[str]`; `add_labels` extends `labels`, `assign_reviewers` extends `reviewers`.

- [ ] **Step 1: Write the failing test**

`tests/test_labels_reviewers.py`:
```python
import json
import httpx
from app.git.github import GitHubAdapter
from app.git.fake import FakeGitAdapter
from tests.fixtures import sample_meta, sample_diff


def test_github_add_labels():
    seen = {}
    def handler(request):
        assert request.url.path == "/repos/o/r/issues/1/labels"
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=[])
    GitHubAdapter("o/r", "t", transport=httpx.MockTransport(handler)).add_labels("o/r", 1, ["size/S"])
    assert seen["labels"] == ["size/S"]


def test_github_assign_reviewers():
    seen = {}
    def handler(request):
        assert request.url.path == "/repos/o/r/pulls/1/requested_reviewers"
        seen.update(json.loads(request.content))
        return httpx.Response(201, json={})
    GitHubAdapter("o/r", "t", transport=httpx.MockTransport(handler)).assign_reviewers("o/r", 1, ["alice"])
    assert seen["reviewers"] == ["alice"]


def test_fake_records_labels_and_reviewers():
    a = FakeGitAdapter(seed={("o/r", 1): (sample_meta(), sample_diff())})
    a.add_labels("o/r", 1, ["type/fix"])
    a.assign_reviewers("o/r", 1, ["bob"])
    assert a.labels == ["type/fix"]
    assert a.reviewers == ["bob"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_labels_reviewers.py -v`
Expected: FAIL — methods missing / adapters abstract.

- [ ] **Step 3: Write minimal implementation**

In `app/git/base.py`, add two abstract methods:
```python
    @abstractmethod
    def add_labels(self, repo: str, pr_number: int, labels: list[str]) -> None: ...

    @abstractmethod
    def assign_reviewers(self, repo: str, pr_number: int, reviewers: list[str]) -> None: ...
```

In `app/git/github.py`, add:
```python
    def add_labels(self, repo, pr_number, labels) -> None:
        self._post(f"/repos/{repo}/issues/{pr_number}/labels", {"labels": labels})

    def assign_reviewers(self, repo, pr_number, reviewers) -> None:
        self._post(f"/repos/{repo}/pulls/{pr_number}/requested_reviewers",
                   {"reviewers": reviewers})
```

In `app/git/fake.py`, add to `__init__`:
```python
        self.labels: list[str] = []
        self.reviewers: list[str] = []
```
and the methods:
```python
    def add_labels(self, repo, pr_number, labels) -> None:
        self.labels.extend(labels)

    def assign_reviewers(self, repo, pr_number, reviewers) -> None:
        self.reviewers.extend(reviewers)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_labels_reviewers.py tests/test_fake_git.py tests/test_github_write.py -v`
Expected: PASS — new tests pass; existing fake/github tests still green (both concretes implement the new methods, so instantiation is unaffected).

- [ ] **Step 5: Commit**

```bash
git add app/git/base.py app/git/github.py app/git/fake.py tests/test_labels_reviewers.py
git commit -m "feat: add_labels and assign_reviewers on git adapter interface"
```

---

### Task 5: Triage task

**Files:**
- Create: `app/tasks/triage.py`
- Modify: `app/reviewer.py` (register `triage`, priority `1`)
- Test: `tests/test_triage.py`

**Interfaces:**
- Consumes: `Task`, `TaskResult`, `Diff`, `PRMeta`, `add_labels`.
- Produces:
  - `class TriageTask(Task)`: `name = "triage"`. Computes deterministic labels and calls `git.add_labels`:
    - size label from `diff.total_changed_lines()`: `<10`→`size/XS`, `<50`→`size/S`, `<200`→`size/M`, `<500`→`size/L`, else `size/XL`.
    - type label from `meta.title` prefix (case-insensitive, before `:` or `(`): `feat`→`type/feature`, `fix`→`type/fix`, `docs`→`type/docs`, `chore`→`type/chore`; no match → no type label.
    - Calls `git.add_labels(repo, pr, labels)` with the non-empty list; returns `TaskResult("triage", 1)` if any label added, else `TaskResult("triage", 0)` (and does not call add_labels for an empty list).
  - Register `TASK_REGISTRY["triage"] = TriageTask`; `_PRIORITY["triage"] = 1`.

- [ ] **Step 1: Write the failing test**

`tests/test_triage.py`:
```python
from app.tasks.triage import TriageTask, _size_label, _type_label
from app.git.fake import FakeGitAdapter
from app.llm.fake import FakeLLMAdapter
from app.models import Diff, FileChange
from tests.fixtures import sample_meta


def _diff(lines):
    return Diff(files=[FileChange(path="a.py", patch="x", additions=lines, deletions=0,
                                 status="modified")])


def test_size_label_buckets():
    assert _size_label(5) == "size/XS"
    assert _size_label(30) == "size/S"
    assert _size_label(150) == "size/M"
    assert _size_label(400) == "size/L"
    assert _size_label(900) == "size/XL"


def test_type_label_from_title():
    assert _type_label("feat: add x") == "type/feature"
    assert _type_label("fix(core): y") == "type/fix"
    assert _type_label("docs: z") == "type/docs"
    assert _type_label("random title") is None


def test_triage_adds_size_and_type_labels():
    git = FakeGitAdapter(seed={("o/r", 1): (sample_meta(title="feat: add x"), _diff(5))})
    llm = FakeLLMAdapter(responses=[""])
    res = TriageTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1),
                           git.get_diff("o/r", 1))
    assert res.posted == 1
    assert "size/XS" in git.labels
    assert "type/feature" in git.labels


def test_triage_no_type_still_adds_size():
    git = FakeGitAdapter(seed={("o/r", 1): (sample_meta(title="random"), _diff(5))})
    llm = FakeLLMAdapter(responses=[""])
    TriageTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1), git.get_diff("o/r", 1))
    assert git.labels == ["size/XS"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_triage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.tasks.triage'`

- [ ] **Step 3: Write minimal implementation**

`app/tasks/triage.py`:
```python
from __future__ import annotations

import re

from app.tasks.base import Task, TaskResult

_TYPE = {"feat": "type/feature", "fix": "type/fix", "docs": "type/docs",
         "chore": "type/chore"}
_PREFIX = re.compile(r"^\s*([a-zA-Z]+)")


def _size_label(lines: int) -> str:
    if lines < 10:
        return "size/XS"
    if lines < 50:
        return "size/S"
    if lines < 200:
        return "size/M"
    if lines < 500:
        return "size/L"
    return "size/XL"


def _type_label(title: str) -> str | None:
    m = _PREFIX.match(title)
    if not m:
        return None
    return _TYPE.get(m.group(1).lower())


class TriageTask(Task):
    name = "triage"

    def run(self, git, llm, repo, pr_number, meta, diff, context=None) -> TaskResult:
        labels = [_size_label(diff.total_changed_lines())]
        t = _type_label(meta.title)
        if t:
            labels.append(t)
        if not labels:
            return TaskResult(self.name, 0)
        git.add_labels(repo, pr_number, labels)
        return TaskResult(self.name, 1)
```

In `app/reviewer.py`, register:
```python
from app.tasks.triage import TriageTask
...
    "triage": TriageTask,
```
(`_PRIORITY` already includes `"triage": 1` from Task 3's update.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_triage.py tests/test_reviewer.py -v`
Expected: PASS (5 triage + reviewer green)

- [ ] **Step 5: Commit**

```bash
git add app/tasks/triage.py app/reviewer.py tests/test_triage.py
git commit -m "feat: triage task with size and type labels"
```

---

### Task 6: README + example config + full suite

**Files:**
- Modify: `README.md`
- Modify: `config.example.yaml`
- Test: full suite

**Interfaces:**
- Consumes: everything above.
- Produces: documented task roster + green suite.

- [ ] **Step 1: Run the full suite**

Run: `pytest -q`
Expected: PASS — all prior tests + all Plan 5 tests, zero network, pristine.

- [ ] **Step 2: Update docs**

Append to `README.md`:
```markdown
## Task roster (slice 5)
All review tasks now available (enable per repo via `tasks:` / `defaults.tasks`):
- `code_review` — inline findings
- `suggest_fixes` — inline GitHub suggestion blocks
- `summarize` — PR summary comment
- `compliance` — gate checklist
- `triage` — size/type labels
- `verdict` — approve / request_changes (a failed `block` gate forces
  request_changes without calling the LLM)

Diffs are secret-redacted before any content is sent to an LLM.
(`qa_reply` — answering @-mentions in threads — is a later slice.)
```
Update `config.example.yaml` `defaults.tasks` to the full list:
```yaml
defaults:
  tasks: [triage, code_review, suggest_fixes, summarize, compliance, verdict]
```

- [ ] **Step 3: Commit**

```bash
git add README.md config.example.yaml
git commit -m "docs: full task roster and redaction note"
```

---

## Self-Review

**Spec coverage (this slice = remaining review tasks §6 + redaction §5 step 6 + block-gate→verdict enforcement §6a):**
- `verdict` task, block-gate enforcement (§6a `block` forces request_changes) → Task 2. ✓
- `suggest_fixes` task with native suggestion blocks (§6) → Task 3. ✓
- `triage` task labels (§6) + adapter `add_labels`/`assign_reviewers` (§4.1) → Tasks 4,5. ✓
- Redaction before LLM (§5 step 6, guardrails) → Task 1. ✓
- Deferred to later slices: `qa_reply` (needs issue_comment webhook parsing + bot-mention trigger), reviewer-assignment heuristics (assign_reviewers implemented but triage doesn't auto-pick reviewers yet), Bitbucket/GitLab, `.pr-agent.yaml` fetch, admin UI, Docker. Adapter interface now carries labels/reviewers so triage/future can use them.

**Placeholder scan:** No TBD/TODO. Suggestion-block backticks are written as ````` in the Task 3 interface note only to avoid nested code-fence ambiguity in this document; the actual code uses literal triple backticks as shown in the Step 3 code block.

**Type consistency:** `Task.run(..., context=None)` identical across verdict/suggest_fixes/triage and the existing tasks. `evaluate_gates(meta, diff, gates)` reused in verdict (Task 2) exactly as in compliance. `Verdict` enum mapping in verdict matches `set_review_verdict(repo, pr, verdict, body)` from the adapter. `add_labels(repo, pr_number, labels)` / `assign_reviewers(repo, pr_number, reviewers)` signatures identical across base/github/fake (Task 4) and called by triage (Task 5). `_render_diff` reused from `code_review` in verdict + suggest_fixes. `_PRIORITY` final map — triage:1, code_review:0, suggest_fixes:3, summarize:5, compliance:7, verdict:9 — consistent across Tasks 3 and 5. `redact_diff(diff) -> Diff` returns the same neutral type the reviewer already passes to tasks (Task 1).
```
