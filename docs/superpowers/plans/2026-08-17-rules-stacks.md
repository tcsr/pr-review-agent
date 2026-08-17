# PR Review Agent — Rules Engine & Stack Packs Implementation Plan (Plan 4 of N)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give reviews teeth and context: deterministic gates (linked issue, PR description, size caps, tests-required, title regex, CI-green) each `block`|`warn`; natural-language review criteria injected into the `code_review` prompt; per-stack auto-detection with built-in rulepacks; and a `compliance` task that posts a gate checklist. All config-driven with global→repo precedence.

**Architecture:** Two pure decision layers — `app/rules` (gates) and `app/stack` (detection + packs) — feed a `ReviewContext` that the reviewer builds once per PR and passes to each task. `code_review` folds the resolved criteria (NL criteria + auto-loaded stack-pack criteria) into its prompt; `compliance` evaluates the gates and posts a checklist. The task-run signature gains an optional `context` argument (default `None`) so existing tasks and tests keep working. Everything is offline-testable — gates and detection are pure functions over the neutral `PRMeta`/`Diff`.

**Tech Stack:** Python 3.11+ (stdlib `re`, `fnmatch`), pydantic v2. No new dependencies.

## Global Constraints

- Python 3.11+ (`from __future__ import annotations`).
- **No network in tests.** Gates/detection/packs are pure functions; task tests use the existing fakes.
- New config is optional and backward-compatible: absent `rules:`/`stacks:` blocks → empty defaults; existing configs keep working.
- `Task.run` gains a trailing optional `context: ReviewContext | None = None`; tasks that don't need it ignore it. The abstract signature and both existing tasks (`code_review`, `summarize`) are updated consistently.
- Gate severity is `block` or `warn`. `block` failures are surfaced as failed checklist items now; enforcing them onto the verdict is the future `verdict` task's job (out of scope here) — do not fake it.
- Rule/stack precedence in this slice is whole-object override: repo-level config wins over global when present (deep-merge and repo `.pr-agent.yaml` fetch are deferred to a later slice — note this, don't build it).
- Stack packs auto-apply when their stack is detected, unless disabled in `stacks.packs`.
- Every code change lands via TDD: failing test first, minimal impl, green, commit.

---

## File Structure

```
app/
  config.py                 # MODIFY: GateConfig, RulesConfig, StacksConfig; RepoConfig +rules/+stacks; Settings +rules/+stacks; resolve_rules(), resolve_stacks()
  rules/
    __init__.py
    gates.py                # GateResult + evaluate_gates(meta, diff, gates) -> list[GateResult]
  stack/
    __init__.py
    detect.py               # detect_stacks(diff) -> set[str]
    packs.py                # BUILTIN_PACKS + pack_criteria(stacks, stacks_cfg) -> list[str]
  review_context.py         # ReviewContext dataclass
  reviewer.py               # MODIFY: build ReviewContext, pass to tasks; review(..., rules=None, stacks_cfg=None)
  tasks/
    base.py                 # MODIFY: run(..., context=None)
    code_review.py          # MODIFY: fold context.review_criteria into prompt
    summarize.py            # MODIFY: accept context param (ignored)
    compliance.py           # ComplianceTask: evaluate gates -> checklist comment
  worker.py                 # MODIFY: resolve rules/stacks, pass to reviewer
tests/
  test_config_rules.py
  test_gates.py
  test_stack_detect.py
  test_stack_packs.py
  test_review_context.py
  test_code_review_criteria.py
  test_compliance.py
  test_worker_rules.py
```

---

### Task 1: Config — rules and stacks models + resolve helpers

**Files:**
- Modify: `app/config.py`
- Test: `tests/test_config_rules.py`

**Interfaces:**
- Produces:
  - `class GateConfig(BaseModel)`: `enabled: bool = True`, `severity: str = "warn"`, `value: int | None = None`, `globs: list[str] | None = None`, `pattern: str | None = None`.
  - `class RulesConfig(BaseModel)`: `gates: dict[str, GateConfig] = {}`, `review_criteria: list[str] = []`, `prompt_overrides: dict[str, str] = {}`.
  - `class StacksConfig(BaseModel)`: `auto_detect: bool = True`, `packs: dict[str, bool] = {}` (a key mapped to `False` disables that built-in pack).
  - `RepoConfig` gains `rules: RulesConfig | None = None`, `stacks: StacksConfig | None = None`.
  - `Settings` gains `rules: RulesConfig = RulesConfig()`, `stacks: StacksConfig = StacksConfig()`; `load_settings` reads optional top-level `rules:`/`stacks:` blocks.
  - `resolve_rules(settings, repo_cfg) -> RulesConfig` — `repo_cfg.rules` if not None else `settings.rules`.
  - `resolve_stacks(settings, repo_cfg) -> StacksConfig` — `repo_cfg.stacks` if not None else `settings.stacks`.

- [ ] **Step 1: Write the failing test**

`tests/test_config_rules.py`:
```python
from app.config import (load_settings, RulesConfig, StacksConfig, GateConfig,
                        RepoConfig, Settings, LLMConfig, StoreConfig,
                        resolve_rules, resolve_stacks)
from app.models import Platform


def _write(tmp_path, text):
    p = tmp_path / "config.yaml"
    p.write_text(text)
    return str(p)


def test_loads_rules_and_stacks(tmp_path):
    path = _write(tmp_path, """
llm: {provider: fake, model: fake}
store: {url: 'sqlite:///:memory:'}
defaults: {tasks: [code_review]}
rules:
  gates:
    require_linked_issue: {enabled: true, severity: warn}
    title_regex: {severity: block, pattern: '^(feat|fix): '}
  review_criteria:
    - "No debug prints."
stacks:
  auto_detect: true
  packs: {angular: false}
repos: []
""")
    s = load_settings(path, env={})
    assert s.rules.gates["title_regex"].severity == "block"
    assert s.rules.gates["title_regex"].pattern == "^(feat|fix): "
    assert s.rules.review_criteria == ["No debug prints."]
    assert s.stacks.packs["angular"] is False


def test_resolve_prefers_repo_over_global():
    global_rules = RulesConfig(review_criteria=["global"])
    repo_rules = RulesConfig(review_criteria=["repo"])
    s = Settings(llm=LLMConfig(), store=StoreConfig(), defaults_tasks=["code_review"],
                 repos=[], rules=global_rules)
    rc_with = RepoConfig(platform=Platform.github, full_name="o/r", token="t", rules=repo_rules)
    rc_without = RepoConfig(platform=Platform.github, full_name="o/r", token="t")
    assert resolve_rules(s, rc_with).review_criteria == ["repo"]
    assert resolve_rules(s, rc_without).review_criteria == ["global"]


def test_resolve_stacks_default_global():
    s = Settings(llm=LLMConfig(), store=StoreConfig(), defaults_tasks=["code_review"], repos=[])
    rc = RepoConfig(platform=Platform.github, full_name="o/r", token="t")
    assert resolve_stacks(s, rc).auto_detect is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config_rules.py -v`
Expected: FAIL — `ImportError: cannot import name 'RulesConfig'`.

- [ ] **Step 3: Write minimal implementation**

In `app/config.py`, add the models (before `RepoConfig`):
```python
class GateConfig(BaseModel):
    enabled: bool = True
    severity: str = "warn"
    value: int | None = None
    globs: list[str] | None = None
    pattern: str | None = None


class RulesConfig(BaseModel):
    gates: dict[str, GateConfig] = {}
    review_criteria: list[str] = []
    prompt_overrides: dict[str, str] = {}


class StacksConfig(BaseModel):
    auto_detect: bool = True
    packs: dict[str, bool] = {}
```
Extend `RepoConfig`:
```python
class RepoConfig(BaseModel):
    platform: Platform
    full_name: str
    token: str
    tasks: list[str] | None = None
    rules: RulesConfig | None = None
    stacks: StacksConfig | None = None
```
Extend `Settings`:
```python
    rules: RulesConfig = RulesConfig()
    stacks: StacksConfig = StacksConfig()
```
In `load_settings`, add to the `Settings(...)` construction:
```python
            rules=RulesConfig(**raw.get("rules", {})),
            stacks=StacksConfig(**raw.get("stacks", {})),
```
Add helpers at module end:
```python
def resolve_rules(settings: "Settings", repo_cfg: RepoConfig) -> RulesConfig:
    return repo_cfg.rules if repo_cfg.rules is not None else settings.rules


def resolve_stacks(settings: "Settings", repo_cfg: RepoConfig) -> StacksConfig:
    return repo_cfg.stacks if repo_cfg.stacks is not None else settings.stacks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config_rules.py tests/test_config.py -v`
Expected: PASS (new 3 + existing config tests green).

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config_rules.py
git commit -m "feat: rules and stacks config models + resolve helpers"
```

---

### Task 2: Gates engine

**Files:**
- Create: `app/rules/__init__.py`
- Create: `app/rules/gates.py`
- Test: `tests/test_gates.py`

**Interfaces:**
- Consumes: `PRMeta`, `Diff`, `GateConfig`.
- Produces:
  - `@dataclass GateResult(name: str, passed: bool, severity: str, message: str)`.
  - `evaluate_gates(meta, diff, gates: dict[str, GateConfig]) -> list[GateResult]` — for each enabled gate in `gates` whose name is known, evaluate and append a `GateResult`. Unknown gate names are skipped. Known gates:
    - `require_linked_issue`: passed if `meta.linked_issues` non-empty.
    - `require_pr_description`: passed if `meta.body.strip()` non-empty.
    - `max_changed_files`: passed if `len(diff.files) <= cfg.value` (cfg.value required; if None, treated as passed).
    - `require_tests_for`: if any changed file path matches any glob in `cfg.globs` (fnmatch), passed only if at least one changed file path contains `"test"` (case-insensitive); if no file matches the globs, passed.
    - `title_regex`: passed if `re.search(cfg.pattern, meta.title)` matches (cfg.pattern required).
    - `ci_must_pass`: passed if `meta.ci_passed is True`.
  - Message is a short human string per gate (pass or fail).

- [ ] **Step 1: Write the failing test**

`tests/test_gates.py`:
```python
from app.rules.gates import evaluate_gates, GateResult
from app.config import GateConfig
from app.models import PRMeta, Diff, FileChange


def _meta(**over):
    base = dict(title="feat: x", body="does a thing", author="a", base_sha="b",
                head_sha="h", labels=[], linked_issues=["#1"], ci_passed=True)
    base.update(over)
    return PRMeta(**base)


def _diff(paths):
    return Diff(files=[FileChange(path=p, patch="", additions=1, deletions=0,
                                  status="modified") for p in paths])


def _by_name(results):
    return {r.name: r for r in results}


def test_require_linked_issue_pass_and_fail():
    g = {"require_linked_issue": GateConfig(severity="warn")}
    assert _by_name(evaluate_gates(_meta(), _diff(["a.py"]), g))["require_linked_issue"].passed
    r = _by_name(evaluate_gates(_meta(linked_issues=[]), _diff(["a.py"]), g))
    assert r["require_linked_issue"].passed is False


def test_max_changed_files():
    g = {"max_changed_files": GateConfig(value=1, severity="warn")}
    assert _by_name(evaluate_gates(_meta(), _diff(["a.py"]), g))["max_changed_files"].passed
    assert _by_name(evaluate_gates(_meta(), _diff(["a.py", "b.py"]), g))["max_changed_files"].passed is False


def test_require_tests_for():
    g = {"require_tests_for": GateConfig(globs=["src/**"], severity="block")}
    # src changed, no test -> fail
    assert _by_name(evaluate_gates(_meta(), _diff(["src/app.py"]), g))["require_tests_for"].passed is False
    # src changed with a test -> pass
    assert _by_name(evaluate_gates(_meta(), _diff(["src/app.py", "tests/test_app.py"]), g))["require_tests_for"].passed
    # no src change -> pass (vacuously)
    assert _by_name(evaluate_gates(_meta(), _diff(["docs/x.md"]), g))["require_tests_for"].passed


def test_title_regex_and_ci():
    g = {"title_regex": GateConfig(pattern="^(feat|fix): ", severity="block"),
         "ci_must_pass": GateConfig(severity="block")}
    r = _by_name(evaluate_gates(_meta(title="chore: y", ci_passed=False), _diff(["a.py"]), g))
    assert r["title_regex"].passed is False
    assert r["ci_must_pass"].passed is False


def test_disabled_gate_skipped():
    g = {"require_linked_issue": GateConfig(enabled=False)}
    assert evaluate_gates(_meta(linked_issues=[]), _diff(["a.py"]), g) == []


def test_unknown_gate_skipped():
    g = {"mystery_gate": GateConfig()}
    assert evaluate_gates(_meta(), _diff(["a.py"]), g) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gates.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.rules'`

- [ ] **Step 3: Write minimal implementation**

`app/rules/__init__.py`: (empty)

`app/rules/gates.py`:
```python
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass


@dataclass
class GateResult:
    name: str
    passed: bool
    severity: str
    message: str


def _matches_any(path: str, globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, g) for g in globs)


def evaluate_gates(meta, diff, gates) -> list[GateResult]:
    results: list[GateResult] = []
    for name, cfg in gates.items():
        if not cfg.enabled:
            continue
        passed, message = _evaluate_one(name, cfg, meta, diff)
        if passed is None:
            continue  # unknown gate
        results.append(GateResult(name=name, passed=passed, severity=cfg.severity,
                                  message=message))
    return results


def _evaluate_one(name, cfg, meta, diff):
    if name == "require_linked_issue":
        ok = bool(meta.linked_issues)
        return ok, "Linked issue present" if ok else "No linked issue in PR body"
    if name == "require_pr_description":
        ok = bool(meta.body.strip())
        return ok, "PR has a description" if ok else "PR description is empty"
    if name == "max_changed_files":
        if cfg.value is None:
            return True, "No file cap configured"
        ok = len(diff.files) <= cfg.value
        return ok, f"{len(diff.files)} files changed (cap {cfg.value})"
    if name == "require_tests_for":
        globs = cfg.globs or []
        touched = any(_matches_any(f.path, globs) for f in diff.files)
        if not touched:
            return True, "No guarded paths changed"
        has_test = any("test" in f.path.lower() for f in diff.files)
        return has_test, "Test change accompanies source" if has_test else "Source changed without a test"
    if name == "title_regex":
        ok = cfg.pattern is not None and re.search(cfg.pattern, meta.title) is not None
        return ok, "Title matches convention" if ok else "Title does not match required pattern"
    if name == "ci_must_pass":
        ok = meta.ci_passed is True
        return ok, "CI is green" if ok else "CI is not green"
    return None, ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gates.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add app/rules tests/test_gates.py
git commit -m "feat: deterministic gates engine"
```

---

### Task 3: Stack detection

**Files:**
- Create: `app/stack/__init__.py`
- Create: `app/stack/detect.py`
- Test: `tests/test_stack_detect.py`

**Interfaces:**
- Consumes: `Diff`.
- Produces:
  - `detect_stacks(diff) -> set[str]` — infers stacks from changed file paths:
    - by extension: `.py`→`python`, `.java`→`java`, `.css`/`.scss`→`css`, `.tsx`/`.jsx`→`react`, `.ts`→`typescript`, `.js`→`javascript`.
    - by filename signal (basename): `angular.json`→`angular`, `nest-cli.json`→`nestjs`, `next.config.js`/`next.config.ts`→`nextjs`, `package.json`→`node`.
    - Returns the union. Empty diff → empty set.

- [ ] **Step 1: Write the failing test**

`tests/test_stack_detect.py`:
```python
from app.stack.detect import detect_stacks
from app.models import Diff, FileChange


def _diff(paths):
    return Diff(files=[FileChange(path=p, patch="", additions=1, deletions=0,
                                  status="modified") for p in paths])


def test_extensions():
    assert detect_stacks(_diff(["a.py"])) == {"python"}
    assert detect_stacks(_diff(["Main.java"])) == {"java"}
    assert detect_stacks(_diff(["a.tsx"])) == {"react"}
    assert "css" in detect_stacks(_diff(["style.scss"]))


def test_filename_signals():
    assert "angular" in detect_stacks(_diff(["angular.json"]))
    assert "nestjs" in detect_stacks(_diff(["nest-cli.json"]))
    assert "nextjs" in detect_stacks(_diff(["next.config.js"]))
    assert "node" in detect_stacks(_diff(["package.json"]))


def test_multi_stack():
    got = detect_stacks(_diff(["src/api/main.ts", "nest-cli.json", "ui/app.tsx"]))
    assert "nestjs" in got and "react" in got


def test_empty():
    assert detect_stacks(_diff([])) == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_stack_detect.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.stack'`

- [ ] **Step 3: Write minimal implementation**

`app/stack/__init__.py`: (empty)

`app/stack/detect.py`:
```python
from __future__ import annotations

import os

_EXT = {
    ".py": "python", ".java": "java", ".css": "css", ".scss": "css",
    ".tsx": "react", ".jsx": "react", ".ts": "typescript", ".js": "javascript",
}
_FILENAME = {
    "angular.json": "angular", "nest-cli.json": "nestjs",
    "next.config.js": "nextjs", "next.config.ts": "nextjs",
    "package.json": "node",
}


def detect_stacks(diff) -> set[str]:
    stacks: set[str] = set()
    for f in diff.files:
        base = os.path.basename(f.path)
        if base in _FILENAME:
            stacks.add(_FILENAME[base])
        ext = os.path.splitext(f.path)[1].lower()
        if ext in _EXT:
            stacks.add(_EXT[ext])
    return stacks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_stack_detect.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add app/stack/__init__.py app/stack/detect.py tests/test_stack_detect.py
git commit -m "feat: stack detection from changed files"
```

---

### Task 4: Stack packs

**Files:**
- Create: `app/stack/packs.py`
- Test: `tests/test_stack_packs.py`

**Interfaces:**
- Consumes: `StacksConfig`.
- Produces:
  - `BUILTIN_PACKS: dict[str, list[str]]` — review-criteria strings per stack for: `angular`, `react`, `nextjs`, `nestjs`, `node`, `java`, `python`, `javascript`, `typescript`, `css` (2-3 criteria each).
  - `pack_criteria(stacks: set[str], stacks_cfg) -> list[str]` — for each detected stack present in `BUILTIN_PACKS` and not disabled (`stacks_cfg.packs.get(stack) is not False`), append its criteria. Deterministic order: iterate `BUILTIN_PACKS` insertion order, include those in `stacks`. Returns a flat list.

- [ ] **Step 1: Write the failing test**

`tests/test_stack_packs.py`:
```python
from app.stack.packs import BUILTIN_PACKS, pack_criteria
from app.config import StacksConfig


def test_builtin_packs_cover_expected_stacks():
    for s in ["angular", "react", "nextjs", "nestjs", "node", "java",
              "python", "javascript", "typescript", "css"]:
        assert s in BUILTIN_PACKS and BUILTIN_PACKS[s]


def test_pack_criteria_includes_detected():
    crit = pack_criteria({"python"}, StacksConfig())
    assert crit == BUILTIN_PACKS["python"]


def test_pack_criteria_disabled_pack_excluded():
    crit = pack_criteria({"react"}, StacksConfig(packs={"react": False}))
    assert crit == []


def test_pack_criteria_unknown_stack_ignored():
    assert pack_criteria({"cobol"}, StacksConfig()) == []


def test_pack_criteria_deterministic_order():
    a = pack_criteria({"python", "react"}, StacksConfig())
    b = pack_criteria({"react", "python"}, StacksConfig())
    assert a == b
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_stack_packs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.stack.packs'`

- [ ] **Step 3: Write minimal implementation**

`app/stack/packs.py`:
```python
from __future__ import annotations

BUILTIN_PACKS: dict[str, list[str]] = {
    "angular": [
        "Use OnPush change detection where possible.",
        "Unsubscribe from observables (takeUntil/async pipe) to avoid leaks.",
        "Keep logic out of templates.",
    ],
    "react": [
        "Verify hook dependency arrays are correct and complete.",
        "Avoid inline object/array props that force child re-renders.",
        "Ensure list items have stable keys.",
    ],
    "nextjs": [
        "Respect server vs client component boundaries ('use client').",
        "Use appropriate data-fetching patterns; avoid client fetch for static data.",
    ],
    "nestjs": [
        "Validate DTOs at boundaries.",
        "Respect module boundaries and injectable scopes.",
    ],
    "node": [
        "Handle async errors; avoid unhandled promise rejections.",
        "Avoid blocking synchronous calls on the event loop.",
    ],
    "java": [
        "Guard against nulls; prefer Optional at boundaries.",
        "Close resources with try-with-resources.",
    ],
    "python": [
        "Add type hints to new public functions.",
        "Avoid mutable default arguments.",
        "Use context managers for resource handling.",
    ],
    "javascript": [
        "No leftover console.log/debugger.",
        "Prefer const/let over var.",
    ],
    "typescript": [
        "Avoid `any`; prefer precise types.",
        "No leftover console.log/debugger.",
    ],
    "css": [
        "Avoid !important and overly specific selectors.",
        "Use responsive units over fixed pixels where appropriate.",
    ],
}


def pack_criteria(stacks: set[str], stacks_cfg) -> list[str]:
    out: list[str] = []
    for stack, criteria in BUILTIN_PACKS.items():
        if stack in stacks and stacks_cfg.packs.get(stack) is not False:
            out.extend(criteria)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_stack_packs.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add app/stack/packs.py tests/test_stack_packs.py
git commit -m "feat: built-in stack rulepacks"
```

---

### Task 5: ReviewContext + task context plumbing + code_review criteria injection

**Files:**
- Create: `app/review_context.py`
- Modify: `app/tasks/base.py` (add `context` param)
- Modify: `app/tasks/code_review.py` (use `context.review_criteria`)
- Modify: `app/tasks/summarize.py` (accept `context` param, ignore)
- Modify: `app/reviewer.py` (build context, pass it, new signature)
- Test: `tests/test_review_context.py`, `tests/test_code_review_criteria.py`

**Interfaces:**
- Consumes: `RulesConfig`, `StacksConfig`, `detect_stacks`, `pack_criteria`, gate config, `PRMeta`, `Diff`.
- Produces:
  - `@dataclass ReviewContext(review_criteria: list[str], gates: dict, stacks: set[str])` (in `app/review_context.py`).
  - `Task.run(self, git, llm, repo, pr_number, meta, diff, context=None) -> TaskResult` — signature updated in the ABC and both existing tasks.
  - `CodeReviewTask.run` — when `context` and `context.review_criteria`, append an "Additional review criteria:" block (one bullet per criterion) to the user prompt.
  - `Reviewer.review(repo, pr_number, tasks, rules=None, stacks_cfg=None) -> list[TaskResult]` — after fetching meta+diff: `stacks = detect_stacks(diff)`; `criteria = (rules.review_criteria if rules else []) + pack_criteria(stacks, stacks_cfg or StacksConfig())`; `gates = rules.gates if rules else {}`; build `ReviewContext(criteria, gates, stacks)`; pass `context=context` to every `task.run`.

- [ ] **Step 1: Write the failing test**

`tests/test_review_context.py`:
```python
from app.review_context import ReviewContext
from app.reviewer import Reviewer
from app.git.fake import FakeGitAdapter
from app.llm.fake import FakeLLMAdapter
from app.config import RulesConfig, StacksConfig
from tests.fixtures import sample_meta, sample_diff


def _git():
    return FakeGitAdapter(seed={("o/r", 1): (sample_meta(), sample_diff())})


def test_review_context_dataclass():
    ctx = ReviewContext(review_criteria=["x"], gates={}, stacks={"python"})
    assert ctx.review_criteria == ["x"]
    assert ctx.stacks == {"python"}


def test_reviewer_passes_criteria_including_pack(monkeypatch):
    # sample_diff has src/app.py -> python stack -> python pack criteria present
    git = _git()
    captured = {}
    def responder(system, msgs):
        captured["prompt"] = msgs[-1].content
        return "[]"
    llm = FakeLLMAdapter(responder=responder)
    rules = RulesConfig(review_criteria=["Custom: no TODOs."])
    Reviewer(git, llm).review("o/r", 1, ["code_review"], rules=rules,
                              stacks_cfg=StacksConfig())
    assert "Custom: no TODOs." in captured["prompt"]
    assert "type hints" in captured["prompt"].lower()  # from python pack
```

`tests/test_code_review_criteria.py`:
```python
from app.tasks.code_review import CodeReviewTask
from app.review_context import ReviewContext
from app.git.fake import FakeGitAdapter
from app.llm.fake import FakeLLMAdapter
from tests.fixtures import sample_meta, sample_diff


def _git():
    return FakeGitAdapter(seed={("o/r", 1): (sample_meta(), sample_diff())})


def test_criteria_appear_in_prompt():
    git = _git()
    captured = {}
    def responder(system, msgs):
        captured["p"] = msgs[-1].content
        return "[]"
    llm = FakeLLMAdapter(responder=responder)
    ctx = ReviewContext(review_criteria=["No secrets.", "Docstrings please."],
                        gates={}, stacks=set())
    CodeReviewTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1),
                         git.get_diff("o/r", 1), context=ctx)
    assert "No secrets." in captured["p"]
    assert "Docstrings please." in captured["p"]


def test_runs_without_context():
    git = _git()
    llm = FakeLLMAdapter(responses=["[]"])
    res = CodeReviewTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1),
                               git.get_diff("o/r", 1))
    assert res.name == "code_review"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_review_context.py tests/test_code_review_criteria.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.review_context'`

- [ ] **Step 3: Write minimal implementation**

`app/review_context.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReviewContext:
    review_criteria: list[str] = field(default_factory=list)
    gates: dict = field(default_factory=dict)
    stacks: set[str] = field(default_factory=set)
```

In `app/tasks/base.py`, update the abstract signature:
```python
    @abstractmethod
    def run(self, git, llm, repo, pr_number, meta, diff, context=None) -> TaskResult: ...
```

In `app/tasks/code_review.py`, update `run` to accept `context=None` and fold criteria in:
```python
    def run(self, git, llm, repo, pr_number, meta, diff, context=None) -> TaskResult:
        prompt = (
            f"PR title: {meta.title}\n\nDiff:\n{_render_diff(diff)}\n\n"
            "List review findings as JSON."
        )
        if context and context.review_criteria:
            bullets = "\n".join(f"- {c}" for c in context.review_criteria)
            prompt += f"\n\nAdditional review criteria:\n{bullets}"
        resp = llm.complete(_SYSTEM, [Message(role="user", content=prompt)], max_tokens=2000)
        # ... unchanged JSON parsing + posting ...
```
(Keep the existing parse/post logic below unchanged.)

In `app/tasks/summarize.py`, update `run` to accept the param:
```python
    def run(self, git, llm, repo, pr_number, meta, diff, context=None) -> TaskResult:
```
(body unchanged.)

In `app/reviewer.py`, update `review` and pass context:
```python
from app.review_context import ReviewContext
from app.config import StacksConfig
from app.stack.detect import detect_stacks
from app.stack.packs import pack_criteria


    def review(self, repo, pr_number, tasks, rules=None, stacks_cfg=None):
        selected = [t for t in tasks if t in TASK_REGISTRY]
        selected.sort(key=lambda t: _PRIORITY.get(t, 100))
        meta = self.git.get_pr_meta(repo, pr_number)
        diff = self.git.get_diff(repo, pr_number)
        stacks = detect_stacks(diff)
        criteria = (list(rules.review_criteria) if rules else [])
        criteria += pack_criteria(stacks, stacks_cfg or StacksConfig())
        gates = rules.gates if rules else {}
        context = ReviewContext(review_criteria=criteria, gates=gates, stacks=stacks)
        results = []
        for name in selected:
            task = TASK_REGISTRY[name]()
            results.append(task.run(self.git, self.llm, repo, pr_number, meta, diff,
                                    context=context))
        return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_review_context.py tests/test_code_review_criteria.py tests/test_reviewer.py tests/test_tasks_code_review.py tests/test_tasks_summarize.py -v`
Expected: PASS — new tests pass; existing task/reviewer tests still green (context defaults to None).

- [ ] **Step 5: Commit**

```bash
git add app/review_context.py app/tasks/base.py app/tasks/code_review.py app/tasks/summarize.py app/reviewer.py tests/test_review_context.py tests/test_code_review_criteria.py
git commit -m "feat: ReviewContext threads criteria + stack packs into code_review"
```

---

### Task 6: Compliance task

**Files:**
- Create: `app/tasks/compliance.py`
- Modify: `app/reviewer.py` (register `compliance` in `TASK_REGISTRY` and `_PRIORITY`)
- Test: `tests/test_compliance.py`

**Interfaces:**
- Consumes: `Task`, `TaskResult`, `evaluate_gates`, `ReviewContext`.
- Produces:
  - `class ComplianceTask(Task)`: `name = "compliance"`. In `run`, if `context` is None or `context.gates` empty → post nothing, return `TaskResult("compliance", 0)`. Otherwise `evaluate_gates(meta, diff, context.gates)`, format a checklist comment (one line per gate: `✅`/`❌` + name + message, with a `(block)`/`(warn)` tag), post via `git.post_comment`, return `TaskResult("compliance", 1)`.
  - `TASK_REGISTRY["compliance"] = ComplianceTask`; `_PRIORITY["compliance"] = 7`.

- [ ] **Step 1: Write the failing test**

`tests/test_compliance.py`:
```python
from app.tasks.compliance import ComplianceTask
from app.review_context import ReviewContext
from app.config import GateConfig
from app.git.fake import FakeGitAdapter
from app.llm.fake import FakeLLMAdapter
from tests.fixtures import sample_meta, sample_diff


def _git(**meta_over):
    return FakeGitAdapter(seed={("o/r", 1): (sample_meta(**meta_over), sample_diff())})


def test_posts_checklist_with_pass_and_fail():
    git = _git(linked_issues=[], ci_passed=False)
    llm = FakeLLMAdapter(responses=[""])
    ctx = ReviewContext(gates={
        "require_linked_issue": GateConfig(severity="warn"),
        "ci_must_pass": GateConfig(severity="block"),
    })
    res = ComplianceTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1),
                               git.get_diff("o/r", 1), context=ctx)
    assert res.posted == 1
    body = git.comments[0].body
    assert "require_linked_issue" in body
    assert "ci_must_pass" in body
    assert "❌" in body  # both fail


def test_no_gates_posts_nothing():
    git = _git()
    llm = FakeLLMAdapter(responses=[""])
    res = ComplianceTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1),
                               git.get_diff("o/r", 1), context=ReviewContext())
    assert res.posted == 0
    assert git.comments == []


def test_no_context_posts_nothing():
    git = _git()
    llm = FakeLLMAdapter(responses=[""])
    res = ComplianceTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1),
                               git.get_diff("o/r", 1))
    assert res.posted == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_compliance.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.tasks.compliance'`

- [ ] **Step 3: Write minimal implementation**

`app/tasks/compliance.py`:
```python
from __future__ import annotations

from app.rules.gates import evaluate_gates
from app.tasks.base import Task, TaskResult


class ComplianceTask(Task):
    name = "compliance"

    def run(self, git, llm, repo, pr_number, meta, diff, context=None) -> TaskResult:
        if context is None or not context.gates:
            return TaskResult(self.name, 0)
        results = evaluate_gates(meta, diff, context.gates)
        if not results:
            return TaskResult(self.name, 0)
        lines = ["### Compliance checklist", ""]
        for r in results:
            mark = "✅" if r.passed else "❌"
            lines.append(f"- {mark} **{r.name}** ({r.severity}): {r.message}")
        git.post_comment(repo, pr_number, "\n".join(lines))
        return TaskResult(self.name, 1)
```

In `app/reviewer.py`, register the task:
```python
from app.tasks.compliance import ComplianceTask

TASK_REGISTRY = {
    "code_review": CodeReviewTask,
    "summarize": SummarizeTask,
    "compliance": ComplianceTask,
}

_PRIORITY = {"code_review": 0, "summarize": 5, "compliance": 7, "verdict": 9}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_compliance.py tests/test_reviewer.py -v`
Expected: PASS (3 compliance + reviewer tests green)

- [ ] **Step 5: Commit**

```bash
git add app/tasks/compliance.py app/reviewer.py tests/test_compliance.py
git commit -m "feat: compliance task posts gate checklist"
```

---

### Task 7: Worker wiring + README + full suite

**Files:**
- Modify: `app/worker.py` (resolve rules/stacks, pass to reviewer)
- Modify: `README.md`
- Test: `tests/test_worker_rules.py`

**Interfaces:**
- Consumes: `resolve_rules`, `resolve_stacks`.
- Produces:
  - `process_one` builds `rules = resolve_rules(settings, repo_cfg)` and `stacks_cfg = resolve_stacks(settings, repo_cfg)` and calls `Reviewer(git, llm).review(job.repo, job.pr_number, [job.task], rules=rules, stacks_cfg=stacks_cfg)`.

- [ ] **Step 1: Write the failing test**

`tests/test_worker_rules.py`:
```python
import httpx
from app.store.db import make_engine, make_session_factory, init_db
from app.queue import Queue
from app.config import (Settings, LLMConfig, StoreConfig, RepoConfig, RulesConfig,
                        GateConfig)
from app.models import Platform
from app.store.tables import Job
from app.worker import process_one


def _queue(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'w.db'}")
    init_db(engine)
    return Queue(make_session_factory(engine))


def _settings():
    return Settings(
        llm=LLMConfig(provider="claude", model="m", api_key="k"),
        store=StoreConfig(url="sqlite:///:memory:"),
        defaults_tasks=["compliance"],
        repos=[RepoConfig(platform=Platform.github, full_name="o/r", token="t",
                          rules=RulesConfig(gates={"ci_must_pass": GateConfig(severity="block")}))],
    )


def _gh(request):
    p = request.url.path
    if p == "/repos/o/r/pulls/1":
        return httpx.Response(200, json={"title": "t", "body": "", "user": {"login": "a"},
                                         "base": {"sha": "b"}, "head": {"sha": "H"}, "labels": []})
    if p == "/repos/o/r/commits/H/status":
        return httpx.Response(200, json={"state": "failure"})
    if p == "/repos/o/r/pulls/1/files":
        return httpx.Response(200, json=[{"filename": "a.py", "patch": "@@",
                                          "additions": 1, "deletions": 0, "status": "modified"}])
    if p == "/repos/o/r/issues/1/comments":
        return httpx.Response(201, json={"id": 1})
    return httpx.Response(404, text=p)


def test_worker_runs_compliance_with_repo_rules(tmp_path):
    q = _queue(tmp_path)
    q.enqueue("github", "o/r", 1, "H", "compliance")
    handled = process_one(q, _settings(), transport_git=httpx.MockTransport(_gh))
    assert handled is True
    with q.session_factory() as s:
        assert s.get(Job, 1).status == "done"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_worker_rules.py -v`
Expected: FAIL — worker calls `review(...)` without rules, so the compliance task sees no gates and posts nothing; but the job still completes. To make this a meaningful RED, the test asserts completion (which already passes) — instead, first change the assertion to check a posted comment by inspecting the mock. Since the mock records nothing, follow this order: run the test against the un-modified worker and confirm it passes trivially, then proceed. **If it already passes, still implement Step 3** (the wiring is required for rules to reach the task; verify by adding the stricter assertion below in Step 3).

Note to implementer: to get a true RED, include this assertion in the test from the start by counting issue-comment POSTs via a shared counter in the `_gh` handler, and assert the compliance comment was posted (≥1). Without the Step-3 wiring, `rules` never reaches the task and no comment is posted → RED; after wiring → GREEN. Add:
```python
posted = {"n": 0}
```
at module level of the test, increment it in the `/issues/1/comments` branch (`posted["n"] += 1; return ...`), and assert `posted["n"] == 1` at the end of the test.

- [ ] **Step 3: Write minimal implementation**

In `app/worker.py`, update the review call:
```python
from app.config import find_repo, resolve_rules, resolve_stacks
...
        git = build_git_adapter(repo_cfg, transport=transport_git)
        llm = build_llm_adapter(settings.llm, transport=transport_llm)
        rules = resolve_rules(settings, repo_cfg)
        stacks_cfg = resolve_stacks(settings, repo_cfg)
        Reviewer(git, llm).review(job.repo, job.pr_number, [job.task],
                                  rules=rules, stacks_cfg=stacks_cfg)
        queue.complete(job.id)
```

- [ ] **Step 4: Run test + full suite**

Run: `pytest tests/test_worker_rules.py -v && pytest -q`
Expected: PASS — the compliance comment is posted (counter == 1), job done; whole suite green, pristine, zero network.

- [ ] **Step 5: Append README + commit**

Append to `README.md`:
```markdown
## Rules & stacks (slice 4)
Reviews are shaped by config:
- **Gates** (deterministic, `block`|`warn`): `require_linked_issue`,
  `require_pr_description`, `max_changed_files`, `require_tests_for`,
  `title_regex`, `ci_must_pass`. The `compliance` task posts a checklist.
- **Review criteria** (natural language) are injected into the `code_review`
  prompt.
- **Stack packs** auto-apply when a stack is detected from changed files
  (Angular, React, Next, NestJS, Node, Java, Python, JS, TS, CSS); disable one
  with `stacks.packs: {angular: false}`.

Configure under top-level `rules:`/`stacks:` (global) or per-repo `rules:`/
`stacks:` (repo overrides global). See `config.example.yaml`.
```
Also add a `rules:`/`stacks:` example block to `config.example.yaml` under the first repo and at top level.

```bash
git add app/worker.py README.md config.example.yaml tests/test_worker_rules.py
git commit -m "feat: worker resolves rules/stacks; docs"
```

---

## Self-Review

**Spec coverage (this slice = spec §6a rules, §6b stacks, and the compliance task from §6):**
- Deterministic gates + `block`/`warn` (§6a A) → Task 2. ✓
- NL review criteria injected into code_review (§6a B) → Task 5. ✓
- Rule sources & precedence — global vs repo whole-object (§6a; deep-merge + `.pr-agent.yaml` deferred) → Task 1. ✓
- Stack detection (§6b) → Task 3. ✓
- Built-in stack rulepacks, auto-apply, disable via config (§6b) → Task 4. ✓
- Compliance task posts checklist (§6 tasks) → Task 6. ✓
- Config models + resolve helpers (§7) → Task 1. ✓
- Worker threads rules/stacks into the run path → Task 7. ✓
- Deferred (noted, not built): deep-merge precedence, repo `.pr-agent.yaml` fetch (needs an adapter get-file method), `prompt_overrides` application, block-gate → verdict enforcement (needs the `verdict` task), remaining tasks (suggest_fixes/triage/qa_reply), Bitbucket/GitLab, UI, Docker.

**Placeholder scan:** No TBD/TODO. Task 7 Step 2 gives explicit RED-construction guidance (a POST counter in the mock) rather than a vague "make it fail" — that is instruction, not a placeholder.

**Type consistency:** `ReviewContext(review_criteria, gates, stacks)` built in reviewer (Task 5), consumed by code_review (Task 5) and compliance (Task 6). `GateConfig` fields (`enabled/severity/value/globs/pattern`) defined in Task 1, consumed by `evaluate_gates` in Task 2 and configured in Tasks 6-7 tests. `evaluate_gates(meta, diff, gates: dict[str,GateConfig]) -> list[GateResult]` — same call shape in Task 2 tests and Task 6 compliance. `Task.run(..., context=None)` signature identical across base, code_review, summarize, compliance (Tasks 5,6). `Reviewer.review(repo, pr, tasks, rules=None, stacks_cfg=None)` — defined Task 5, called by worker Task 7. `resolve_rules`/`resolve_stacks` defined Task 1, used Task 7. `pack_criteria(stacks, stacks_cfg)` defined Task 4, used in reviewer Task 5. `detect_stacks(diff)` defined Task 3, used Task 5.
```
