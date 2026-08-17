from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Platform(str, Enum):
    github = "github"
    bitbucket = "bitbucket"
    gitlab = "gitlab"


class Verdict(str, Enum):
    approve = "approve"
    request_changes = "request_changes"
    comment = "comment"


class Side(str, Enum):
    left = "left"
    right = "right"


@dataclass
class FileChange:
    path: str
    patch: str
    additions: int
    deletions: int
    status: str


@dataclass
class Diff:
    files: list[FileChange]

    def total_changed_lines(self) -> int:
        return sum(f.additions + f.deletions for f in self.files)


@dataclass
class PRMeta:
    title: str
    body: str
    author: str
    base_sha: str
    head_sha: str
    labels: list[str] = field(default_factory=list)
    linked_issues: list[str] = field(default_factory=list)
    ci_passed: bool | None = None


@dataclass
class PR:
    platform: Platform
    repo: str
    number: int
    head_sha: str


@dataclass
class Comment:
    id: str
    author: str
    body: str
    path: str | None = None
    line: int | None = None


@dataclass
class Event:
    platform: Platform
    repo: str
    pr_number: int
    head_sha: str
    action: str
    comment_body: str | None = None
