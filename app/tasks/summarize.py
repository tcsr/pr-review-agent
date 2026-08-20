from __future__ import annotations

from app.llm.base import Message
from app.tasks.base import Task, TaskResult
from app.tasks.code_review import _render_diff

_SYSTEM = "Summarize this pull request in 3-5 sentences: what changed and why."


class SummarizeTask(Task):
    name = "summarize"

    def run(self, git, llm, repo, pr_number, meta, diff, context=None) -> TaskResult:
        prompt = f"Title: {meta.title}\nDescription: {meta.body}\n\nDiff:\n{_render_diff(diff)}"
        if context and getattr(context, "truncated", False):
            prompt += ("\n\nNote: the diff was truncated to fit the token budget; "
                       "some files were not reviewed.")
        resp = llm.complete(_SYSTEM, [Message(role="user", content=prompt)], max_tokens=800)
        if not resp.text.strip():
            return TaskResult(self.name, 0)
        git.post_comment(repo, pr_number, resp.text.strip())
        return TaskResult(self.name, 1)
