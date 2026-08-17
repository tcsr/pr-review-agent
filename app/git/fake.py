from __future__ import annotations

from itertools import count

from app.git.base import GitPlatformAdapter
from app.models import PRMeta, Diff, Comment, Verdict, Side


class FakeGitAdapter(GitPlatformAdapter):
    def __init__(self, seed: dict[tuple[str, int], tuple[PRMeta, Diff]] | None = None):
        self._seed = seed or {}
        self.comments: list[Comment] = []
        self.inline_comments: list[Comment] = []
        self.verdicts: list[tuple[Verdict, str]] = []
        self.replies: list[Comment] = []
        self._ids = count(1)

    def _next_id(self) -> str:
        return f"c{next(self._ids)}"

    def get_pr_meta(self, repo, pr_number):
        return self._seed[(repo, pr_number)][0]

    def get_diff(self, repo, pr_number):
        return self._seed[(repo, pr_number)][1]

    def post_comment(self, repo, pr_number, body):
        c = Comment(id=self._next_id(), author="bot", body=body)
        self.comments.append(c)
        return c.id

    def post_inline_comment(self, repo, pr_number, path, line, body, side: Side):
        c = Comment(id=self._next_id(), author="bot", body=body, path=path, line=line)
        self.inline_comments.append(c)
        return c.id

    def set_review_verdict(self, repo, pr_number, verdict: Verdict, body):
        self.verdicts.append((verdict, body))

    def get_thread(self, repo, pr_number):
        return list(self.comments)

    def reply(self, repo, pr_number, in_reply_to, body):
        c = Comment(id=self._next_id(), author="bot", body=body)
        self.replies.append(c)
        return c.id
