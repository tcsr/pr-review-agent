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
