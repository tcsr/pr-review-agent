from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.git.base import GitPlatformAdapter
from app.llm.base import LLMAdapter
from app.models import PRMeta, Diff


@dataclass
class TaskResult:
    name: str
    posted: int


class Task(ABC):
    name: str = "task"

    @abstractmethod
    def run(self, git: GitPlatformAdapter, llm: LLMAdapter, repo: str,
            pr_number: int, meta: PRMeta, diff: Diff, context=None) -> TaskResult: ...
