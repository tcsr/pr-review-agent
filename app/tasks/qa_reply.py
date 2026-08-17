from __future__ import annotations

from app.llm.base import Message
from app.tasks.base import Task, TaskResult
from app.tasks.code_review import _render_diff

_SYSTEM = (
    "You are a helpful PR review bot. Answer the reviewer's question about this "
    "pull request concisely, using the diff for context."
)


class QaReplyTask(Task):
    name = "qa_reply"

    def run(self, git, llm, repo, pr_number, meta, diff, context=None) -> TaskResult:
        handle = context.bot_handle if context else ""
        if not handle:
            return TaskResult(self.name, 0)
        needle = f"@{handle}".lower()
        thread = git.get_thread(repo, pr_number)
        mention = None
        for c in thread:
            if needle in c.body.lower() and c.author != handle:
                mention = c
        if mention is None:
            return TaskResult(self.name, 0)
        prompt = (f"Question: {mention.body}\n\nPR title: {meta.title}\n\n"
                  f"Diff:\n{_render_diff(diff)}\n\nAnswer the question.")
        resp = llm.complete(_SYSTEM, [Message(role="user", content=prompt)], max_tokens=800)
        if not resp.text.strip():
            return TaskResult(self.name, 0)
        git.reply(repo, pr_number, mention.id, resp.text.strip())
        return TaskResult(self.name, 1)
