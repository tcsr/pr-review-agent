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
