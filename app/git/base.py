from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import PRMeta, Diff, Comment, Verdict, Side, PR


class GitPlatformAdapter(ABC):
    @abstractmethod
    def get_pr_meta(self, repo: str, pr_number: int) -> PRMeta: ...

    @abstractmethod
    def get_diff(self, repo: str, pr_number: int) -> Diff: ...

    @abstractmethod
    def post_comment(self, repo: str, pr_number: int, body: str) -> str: ...

    @abstractmethod
    def post_inline_comment(self, repo: str, pr_number: int, path: str,
                            line: int, body: str, side: Side) -> str: ...

    @abstractmethod
    def set_review_verdict(self, repo: str, pr_number: int, verdict: Verdict,
                           body: str) -> None: ...

    @abstractmethod
    def get_thread(self, repo: str, pr_number: int) -> list[Comment]: ...

    @abstractmethod
    def reply(self, repo: str, pr_number: int, in_reply_to: str, body: str) -> str: ...

    @abstractmethod
    def list_open_prs(self, repo: str) -> list[PR]: ...

    @abstractmethod
    def add_labels(self, repo: str, pr_number: int, labels: list[str]) -> None: ...

    @abstractmethod
    def assign_reviewers(self, repo: str, pr_number: int, reviewers: list[str]) -> None: ...
