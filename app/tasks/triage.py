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
