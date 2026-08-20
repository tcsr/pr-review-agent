# PR Review Agent — Production Hardening Plan (Plan 9 of N)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close three real production gaps: (1) enforce the LLM token budget — skip generated/lock files and truncate oversized diffs instead of sending unbounded prompts; (2) make PR-level comments idempotent — re-review edits the prior bot comment instead of stacking duplicates; (3) add CI so the repo's own 178 tests run on every push/PR.

**Architecture:** A pure `app/budget.py` trims a `Diff` (drop `skip_globs`, keep most-changed files within `max_tokens_per_pr`, report whether it truncated); the reviewer applies it after redaction and passes a `truncated` flag through `ReviewContext` so `code_review`/`summarize` note it. A new `update_comment` adapter method plus a `post_or_update` helper let `summarize`/`compliance` tag their comment with a hidden marker and edit it on re-run. A GitHub Actions workflow runs `pytest`. All new logic is offline-testable.

**Tech Stack:** Python 3.11+ (stdlib `fnmatch`), FastAPI/httpx (existing), GitHub Actions YAML. No new runtime dependency.

## Global Constraints

- Python 3.11+ (`from __future__ import annotations`).
- **No network in tests.** Budget is a pure function; idempotency tested via `FakeGitAdapter`; CI file validated by YAML parsing.
- Backward compatible: `Reviewer.review` gains optional `max_tokens_per_pr=None`/`skip_globs=None` (None → no budgeting, existing tests unaffected). `update_comment` is a new abstract method — both concrete adapters (`GitHubAdapter`, `FakeGitAdapter`) must implement it.
- Token counting uses the LLM adapter's existing `count_tokens`; budgeting keeps the most-changed files (by additions+deletions) that fit, and marks `truncated` only when files are dropped for BUDGET reasons (skip-glob drops are not "truncation").
- Idempotency markers are HTML comments (`<!-- pr-agent:<task> -->`) invisible in rendered markdown; a task finds its own prior comment in the thread by marker and edits it, else posts a new tagged comment.
- Only PR-level `post_comment` tasks (`summarize`, `compliance`) get idempotency this slice; `verdict` uses `set_review_verdict` (GitHub shows the latest review state, no stacking problem) and inline-comment tasks are out of scope (noted).
- Every code change lands via TDD: failing test first, minimal impl, green, commit.

---

## File Structure

```
app/
  config.py                 # MODIFY: Settings.skip_globs (from defaults.skip_globs)
  budget.py                 # apply_budget(diff, count_tokens, max_tokens, skip_globs) -> (Diff, bool)
  review_context.py         # MODIFY: ReviewContext.truncated: bool = False
  reviewer.py               # MODIFY: apply budget; review(..., max_tokens_per_pr=None, skip_globs=None)
  worker.py                 # MODIFY: pass settings.llm.max_tokens_per_pr + settings.skip_globs
  git/base.py               # MODIFY: add abstract update_comment
  git/github.py             # MODIFY: implement update_comment (PATCH issue comment)
  git/fake.py               # MODIFY: implement update_comment (mutate recorded comment)
  tasks/comments.py         # post_or_update(git, repo, pr, marker, body) -> str
  tasks/summarize.py        # MODIFY: post_or_update + truncation note
  tasks/compliance.py       # MODIFY: post_or_update
  tasks/code_review.py      # MODIFY: truncation note in prompt
.github/workflows/ci.yml
tests/
  test_budget.py
  test_reviewer_budget.py
  test_update_comment.py
  test_idempotent_comments.py
  test_ci_workflow.py
```

---

### Task 1: Config skip_globs + budget module

**Files:**
- Modify: `app/config.py` (`Settings.skip_globs`)
- Create: `app/budget.py`
- Test: `tests/test_config.py` (one case), `tests/test_budget.py`

**Interfaces:**
- Produces:
  - `Settings` gains `skip_globs: list[str] = []`; `load_settings` reads `raw["defaults"].get("skip_globs", [])`.
  - `apply_budget(diff, count_tokens, max_tokens: int, skip_globs: list[str]) -> tuple[Diff, bool]` — drop files whose path matches any `skip_globs` (fnmatch); of the rest, keep the most-changed (by `additions+deletions`, desc) whose cumulative `count_tokens(patch)` stays ≤ `max_tokens` (always keep at least one candidate); return `(Diff(kept), truncated)` where `truncated` is True iff a NON-skipped file was dropped for budget.

- [ ] **Step 1: Write the failing test**

`tests/test_budget.py`:
```python
from app.budget import apply_budget
from app.models import Diff, FileChange


def _fc(path, patch, adds=1, dels=0):
    return FileChange(path=path, patch=patch, additions=adds, deletions=dels, status="modified")


def _count(text):
    return len(text.split())


def test_skip_globs_dropped_not_truncation():
    diff = Diff(files=[_fc("a.py", "x y"), _fc("pkg.lock", "a b c d")])
    out, truncated = apply_budget(diff, _count, 1000, ["*.lock"])
    assert [f.path for f in out.files] == ["a.py"]
    assert truncated is False   # skip is intentional, not truncation


def test_truncates_when_over_budget():
    diff = Diff(files=[_fc("big.py", "w " * 50, adds=50), _fc("small.py", "z", adds=1)])
    # budget fits only the bigger file (~50 tokens); small dropped
    out, truncated = apply_budget(diff, _count, 50, [])
    assert [f.path for f in out.files] == ["big.py"]
    assert truncated is True


def test_no_truncation_when_all_fit():
    diff = Diff(files=[_fc("a.py", "x"), _fc("b.py", "y")])
    out, truncated = apply_budget(diff, _count, 1000, [])
    assert len(out.files) == 2
    assert truncated is False


def test_keeps_at_least_one_when_first_exceeds():
    diff = Diff(files=[_fc("huge.py", "t " * 100, adds=100)])
    out, truncated = apply_budget(diff, _count, 10, [])
    assert len(out.files) == 1     # never drop everything
    assert truncated is False      # only one candidate, none dropped
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_budget.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.budget'`

- [ ] **Step 3: Write minimal implementation**

In `app/config.py`, add `skip_globs: list[str] = []` to `Settings`, and in `load_settings`'s `Settings(...)`:
```python
            skip_globs=raw["defaults"].get("skip_globs", []),
```

`app/budget.py`:
```python
from __future__ import annotations

import fnmatch

from app.models import Diff


def apply_budget(diff, count_tokens, max_tokens: int, skip_globs: list[str]) -> tuple[Diff, bool]:
    candidates = [f for f in diff.files
                  if not any(fnmatch.fnmatch(f.path, g) for g in skip_globs)]
    ordered = sorted(candidates, key=lambda f: f.additions + f.deletions, reverse=True)
    kept, used = [], 0
    for f in ordered:
        cost = count_tokens(f.patch)
        if kept and used + cost > max_tokens:
            continue
        kept.append(f)
        used += cost
    truncated = len(kept) < len(candidates)
    return Diff(files=kept), truncated
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_budget.py tests/test_config.py -v`
Expected: PASS (4 budget + config green)

- [ ] **Step 5: Commit**

```bash
git add app/config.py app/budget.py tests/test_budget.py tests/test_config.py
git commit -m "feat: skip_globs config and diff token-budget helper"
```

---

### Task 2: Reviewer applies budget + truncation note

**Files:**
- Modify: `app/review_context.py` (`truncated`)
- Modify: `app/reviewer.py` (apply budget, new params)
- Modify: `app/tasks/code_review.py` (truncation note)
- Modify: `app/tasks/summarize.py` (truncation note)
- Modify: `app/worker.py` (pass budget params)
- Test: `tests/test_reviewer_budget.py`

**Interfaces:**
- Produces:
  - `ReviewContext` gains `truncated: bool = False`.
  - `Reviewer.review(repo, pr_number, tasks, rules=None, stacks_cfg=None, bot_handle="", max_tokens_per_pr=None, skip_globs=None)` — after redaction, if `max_tokens_per_pr` is not None: `diff, truncated = apply_budget(diff, self.llm.count_tokens, max_tokens_per_pr, skip_globs or [])`; put `truncated` on the `ReviewContext`.
  - `code_review` and `summarize`: when `context and context.truncated`, append a line to their LLM prompt: `"\n\nNote: the diff was truncated to fit the token budget; some files were not reviewed."`.
  - `worker.process_one` passes `max_tokens_per_pr=settings.llm.max_tokens_per_pr, skip_globs=settings.skip_globs`.

- [ ] **Step 1: Write the failing test**

`tests/test_reviewer_budget.py`:
```python
from app.reviewer import Reviewer
from app.git.fake import FakeGitAdapter
from app.llm.fake import FakeLLMAdapter
from app.models import PRMeta, Diff, FileChange


def _meta():
    return PRMeta(title="t", body="", author="a", base_sha="b", head_sha="h",
                  labels=[], linked_issues=[], ci_passed=True)


def _big_diff():
    return Diff(files=[
        FileChange(path="a.py", patch="w " * 40, additions=40, deletions=0, status="modified"),
        FileChange(path="b.py", patch="z " * 40, additions=40, deletions=0, status="modified"),
    ])


def _git():
    return FakeGitAdapter(seed={("o/r", 1): (_meta(), _big_diff())})


def test_budget_truncates_and_notes():
    git = _git()
    captured = {}
    def responder(system, msgs):
        captured["prompt"] = msgs[-1].content
        return "[]"
    llm = FakeLLMAdapter(responder=responder)
    # budget fits ~one 40-token file
    Reviewer(git, llm).review("o/r", 1, ["code_review"], max_tokens_per_pr=40, skip_globs=[])
    assert "truncated" in captured["prompt"].lower()


def test_no_budget_no_note():
    git = _git()
    captured = {}
    def responder(system, msgs):
        captured["prompt"] = msgs[-1].content
        return "[]"
    llm = FakeLLMAdapter(responder=responder)
    Reviewer(git, llm).review("o/r", 1, ["code_review"])  # no budget
    assert "truncated" not in captured["prompt"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reviewer_budget.py -v`
Expected: FAIL — reviewer has no `max_tokens_per_pr` param / no truncation note.

- [ ] **Step 3: Write minimal implementation**

`app/review_context.py`: add `truncated: bool = False` field (after `bot_handle`).

`app/reviewer.py`: import `apply_budget`; update signature and body:
```python
from app.budget import apply_budget
...
    def review(self, repo, pr_number, tasks, rules=None, stacks_cfg=None, bot_handle="",
               max_tokens_per_pr=None, skip_globs=None):
        selected = [t for t in tasks if t in TASK_REGISTRY]
        selected.sort(key=lambda t: _PRIORITY.get(t, 100))
        meta = self.git.get_pr_meta(repo, pr_number)
        diff = redact_diff(self.git.get_diff(repo, pr_number))
        truncated = False
        if max_tokens_per_pr is not None:
            diff, truncated = apply_budget(diff, self.llm.count_tokens,
                                           max_tokens_per_pr, skip_globs or [])
        stacks = detect_stacks(diff)
        criteria = (list(rules.review_criteria) if rules else [])
        criteria += pack_criteria(stacks, stacks_cfg or StacksConfig())
        gates = rules.gates if rules else {}
        context = ReviewContext(review_criteria=criteria, gates=gates, stacks=stacks,
                                bot_handle=bot_handle, truncated=truncated)
        results = []
        for name in selected:
            task = TASK_REGISTRY[name]()
            results.append(task.run(self.git, self.llm, repo, pr_number, meta, diff,
                                    context=context))
        return results
```

`app/tasks/code_review.py`: in `run`, after building `prompt` and before the criteria block (or after — anywhere before `llm.complete`), add:
```python
        if context and getattr(context, "truncated", False):
            prompt += ("\n\nNote: the diff was truncated to fit the token budget; "
                       "some files were not reviewed.")
```

`app/tasks/summarize.py`: in `run`, after building `prompt`:
```python
        if context and getattr(context, "truncated", False):
            prompt += ("\n\nNote: the diff was truncated to fit the token budget; "
                       "some files were not reviewed.")
```

`app/worker.py`: update the `review(...)` call to add:
```python
                                  max_tokens_per_pr=settings.llm.max_tokens_per_pr,
                                  skip_globs=settings.skip_globs)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reviewer_budget.py tests/test_reviewer.py tests/test_worker.py tests/test_worker_rules.py -v`
Expected: PASS — new budget tests pass; existing reviewer/worker tests still green (no budget passed → truncated False).

- [ ] **Step 5: Commit**

```bash
git add app/review_context.py app/reviewer.py app/tasks/code_review.py app/tasks/summarize.py app/worker.py tests/test_reviewer_budget.py
git commit -m "feat: enforce token budget in reviewer with truncation note"
```

---

### Task 3: update_comment adapter method

**Files:**
- Modify: `app/git/base.py` (abstract `update_comment`)
- Modify: `app/git/github.py` (implement)
- Modify: `app/git/fake.py` (implement)
- Test: `tests/test_update_comment.py`

**Interfaces:**
- Produces:
  - `GitPlatformAdapter.update_comment(repo: str, pr_number: int, comment_id: str, body: str) -> None` (new abstract).
  - `GitHubAdapter.update_comment` — PATCH `/repos/{repo}/issues/comments/{comment_id}` with `{body}`.
  - `FakeGitAdapter.update_comment` — find the `Comment` in `self.comments` whose `id == comment_id`, replace its `body`; also append `(comment_id, body)` to a new public list `self.updates`.

- [ ] **Step 1: Write the failing test**

`tests/test_update_comment.py`:
```python
import httpx
from app.git.github import GitHubAdapter
from app.git.fake import FakeGitAdapter
from app.models import Comment
from tests.fixtures import sample_meta, sample_diff


def test_github_update_comment_patches():
    seen = {}
    def handler(request):
        import json
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": 5})
    a = GitHubAdapter("o/r", "t", transport=httpx.MockTransport(handler))
    a.update_comment("o/r", 1, "5", "new body")
    assert seen["method"] == "PATCH"
    assert seen["path"] == "/repos/o/r/issues/comments/5"
    assert seen["body"]["body"] == "new body"


def test_fake_update_comment_mutates():
    a = FakeGitAdapter(seed={("o/r", 1): (sample_meta(), sample_diff())})
    cid = a.post_comment("o/r", 1, "old")
    a.update_comment("o/r", 1, cid, "new")
    assert a.comments[0].body == "new"
    assert a.updates[0] == (cid, "new")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_update_comment.py -v`
Expected: FAIL — `AttributeError`/abstract method missing.

- [ ] **Step 3: Write minimal implementation**

In `app/git/base.py`, add:
```python
    @abstractmethod
    def update_comment(self, repo: str, pr_number: int, comment_id: str,
                       body: str) -> None: ...
```

In `app/git/github.py`, add a method (use the client's PATCH — add a `_patch` helper mirroring `_post`, or call the client directly):
```python
    def update_comment(self, repo, pr_number, comment_id, body) -> None:
        resp = self._client.patch(
            f"/repos/{repo}/issues/comments/{comment_id}", json={"body": body})
        raise_for_status(resp)
```
(Ensure `raise_for_status` is imported in `github.py` — it already is.)

In `app/git/fake.py`, add to `__init__`: `self.updates: list[tuple[str, str]] = []`, and:
```python
    def update_comment(self, repo, pr_number, comment_id, body) -> None:
        for c in self.comments:
            if c.id == comment_id:
                c.body = body
        self.updates.append((comment_id, body))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_update_comment.py tests/test_fake_git.py tests/test_github_read.py tests/test_github_write.py -v`
Expected: PASS — new tests + existing adapter tests green (both concretes implement the new method, so they still instantiate).

- [ ] **Step 5: Commit**

```bash
git add app/git/base.py app/git/github.py app/git/fake.py tests/test_update_comment.py
git commit -m "feat: update_comment on git adapter interface, github, fake"
```

---

### Task 4: Idempotent post_or_update for summarize + compliance

**Files:**
- Create: `app/tasks/comments.py`
- Modify: `app/tasks/summarize.py` (use `post_or_update`)
- Modify: `app/tasks/compliance.py` (use `post_or_update`)
- Test: `tests/test_idempotent_comments.py`

**Interfaces:**
- Produces:
  - `post_or_update(git, repo, pr_number, marker: str, body: str) -> str` (in `app/tasks/comments.py`) — appends `\n\n<!-- {marker} -->` to `body`; scans `git.get_thread(repo, pr_number)` for a comment whose body contains `marker`; if found, `git.update_comment(repo, pr_number, c.id, tagged)` and returns `c.id`; else `git.post_comment(repo, pr_number, tagged)`.
  - `summarize` posts via `post_or_update(..., "pr-agent:summarize", text)`.
  - `compliance` posts via `post_or_update(..., "pr-agent:compliance", body)`.

- [ ] **Step 1: Write the failing test**

`tests/test_idempotent_comments.py`:
```python
from app.tasks.comments import post_or_update
from app.tasks.summarize import SummarizeTask
from app.git.fake import FakeGitAdapter
from app.llm.fake import FakeLLMAdapter
from tests.fixtures import sample_meta, sample_diff


def _git():
    return FakeGitAdapter(seed={("o/r", 1): (sample_meta(), sample_diff())})


def test_post_or_update_posts_then_updates():
    git = _git()
    first = post_or_update(git, "o/r", 1, "pr-agent:x", "first body")
    assert len(git.comments) == 1
    assert "<!-- pr-agent:x -->" in git.comments[0].body
    second = post_or_update(git, "o/r", 1, "pr-agent:x", "second body")
    assert second == first             # same comment
    assert len(git.comments) == 1      # not duplicated
    assert "second body" in git.comments[0].body
    assert len(git.updates) == 1


def test_summarize_is_idempotent_on_rerun():
    git = _git()
    llm = FakeLLMAdapter(responses=["A summary."])
    SummarizeTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1), git.get_diff("o/r", 1))
    llm2 = FakeLLMAdapter(responses=["A summary."])
    SummarizeTask().run(git, llm2, "o/r", 1, git.get_pr_meta("o/r", 1), git.get_diff("o/r", 1))
    assert len(git.comments) == 1      # re-run edited, not stacked
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_idempotent_comments.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.tasks.comments'`

- [ ] **Step 3: Write minimal implementation**

`app/tasks/comments.py`:
```python
from __future__ import annotations


def post_or_update(git, repo, pr_number, marker: str, body: str) -> str:
    tagged = f"{body}\n\n<!-- {marker} -->"
    for c in git.get_thread(repo, pr_number):
        if marker in (c.body or ""):
            git.update_comment(repo, pr_number, c.id, tagged)
            return c.id
    return git.post_comment(repo, pr_number, tagged)
```

In `app/tasks/summarize.py`, replace the `git.post_comment(...)` line:
```python
from app.tasks.comments import post_or_update
...
        post_or_update(git, repo, pr_number, "pr-agent:summarize", resp.text.strip())
        return TaskResult(self.name, 1)
```

In `app/tasks/compliance.py`, replace the `git.post_comment(...)` line:
```python
from app.tasks.comments import post_or_update
...
        post_or_update(git, repo, pr_number, "pr-agent:compliance", "\n".join(lines))
        return TaskResult(self.name, 1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_idempotent_comments.py tests/test_tasks_summarize.py tests/test_compliance.py -v`
Expected: PASS — idempotency works; existing summarize/compliance tests still green (they assert substrings of the body, which still contain the text). If any existing test asserts an exact `==` body match, update it to check the substring (the marker is appended); note this in the report.

- [ ] **Step 5: Commit**

```bash
git add app/tasks/comments.py app/tasks/summarize.py app/tasks/compliance.py tests/test_idempotent_comments.py
git commit -m "feat: idempotent PR comments for summarize and compliance"
```

---

### Task 5: CI workflow + README + full suite

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `README.md`
- Test: `tests/test_ci_workflow.py`

**Interfaces:**
- Produces: a GitHub Actions workflow running the suite; a test validating its shape.

- [ ] **Step 1: Write the failing test**

`tests/test_ci_workflow.py`:
```python
import os
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_ci_runs_pytest():
    with open(os.path.join(ROOT, ".github", "workflows", "ci.yml")) as f:
        data = yaml.safe_load(f)
    # triggers on push and pull_request
    on = data.get("on") or data.get(True)  # yaml parses bare `on:` as True
    assert on is not None
    text = yaml.dump(data)
    assert "pytest" in text
    assert "pip install" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ci_workflow.py -v`
Expected: FAIL — the workflow file does not exist.

- [ ] **Step 3: Write minimal implementation**

`.github/workflows/ci.yml`:
```yaml
name: CI
on:
  push:
    branches: [master]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install
        run: pip install -e ".[dev]"
      - name: Test
        run: pytest -q
```

- [ ] **Step 4: Run test + full suite**

Run: `pytest tests/test_ci_workflow.py -v && pytest -q`
Expected: PASS — CI test passes; whole suite green, pristine, zero network.

- [ ] **Step 5: Append README + commit**

Append to `README.md`:
```markdown
## Hardening (slice 9)
- **Token budget:** oversized diffs are trimmed to `llm.max_tokens_per_pr` —
  files matching `defaults.skip_globs` (e.g. `*.lock`, `dist/**`) are dropped,
  then the most-changed files are kept within budget; the review notes when a
  diff was truncated.
- **Idempotent comments:** `summarize` and `compliance` tag their comment with a
  hidden marker and edit it on re-review instead of posting duplicates.
- **CI:** `.github/workflows/ci.yml` runs the test suite on every push and PR.
```
Add a `skip_globs` example under `defaults:` in `config.example.yaml`:
```yaml
defaults:
  tasks: [triage, code_review, suggest_fixes, summarize, compliance, verdict]
  skip_globs: ["*.lock", "dist/**", "vendor/**", "*.min.js"]
```

```bash
git add .github/workflows/ci.yml README.md config.example.yaml tests/test_ci_workflow.py
git commit -m "feat: CI workflow and hardening docs"
```

---

## Self-Review

**Coverage of the three targeted gaps:**
- (1) Token budget — `skip_globs` + `apply_budget` (Task 1), wired in reviewer with a truncation note and worker plumbing (Task 2). ✓
- (2) Idempotent PR comments — `update_comment` adapter method (Task 3) + `post_or_update` helper wired into `summarize`/`compliance` (Task 4). ✓
- (3) CI — GitHub Actions workflow running the suite (Task 5). ✓
- Explicitly out of scope (noted): inline-comment idempotency (`code_review`/`suggest_fixes` post many positioned comments — mapping each across re-runs is a larger design); `verdict` idempotency (uses `set_review_verdict`, which GitHub renders as latest-state, no stacking).

**Placeholder scan:** No TBD/TODO. Task 5's test handles PyYAML parsing bare `on:` as boolean `True` explicitly rather than assuming a string key.

**Type consistency:** `apply_budget(diff, count_tokens, max_tokens, skip_globs) -> (Diff, bool)` (Task 1) called by reviewer with `self.llm.count_tokens` (Task 2). `ReviewContext.truncated` (Task 2) read by `code_review`/`summarize`. `Reviewer.review(..., max_tokens_per_pr=None, skip_globs=None)` (Task 2) called by worker with `settings.llm.max_tokens_per_pr` + `settings.skip_globs` (Tasks 1,2). `update_comment(repo, pr_number, comment_id, body)` identical across base/github/fake (Task 3) and called by `post_or_update` (Task 4). `post_or_update(git, repo, pr_number, marker, body) -> str` used by `summarize`/`compliance` (Task 4). `FakeGitAdapter.updates` list added in Task 3, asserted in Tasks 3,4 tests.
