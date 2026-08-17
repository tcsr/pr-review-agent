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
