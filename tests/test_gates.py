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
