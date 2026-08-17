from __future__ import annotations

from app.tasks.base import Task, TaskResult
from app.tasks.code_review import CodeReviewTask
from app.tasks.summarize import SummarizeTask

TASK_REGISTRY: dict[str, type[Task]] = {
    "code_review": CodeReviewTask,
    "summarize": SummarizeTask,
}

# Lower number runs earlier. code_review before verdict (verdict added later).
_PRIORITY = {"code_review": 0, "summarize": 5, "verdict": 9}


class Reviewer:
    def __init__(self, git, llm):
        self.git = git
        self.llm = llm

    def review(self, repo: str, pr_number: int, tasks: list[str]) -> list[TaskResult]:
        selected = [t for t in tasks if t in TASK_REGISTRY]
        selected.sort(key=lambda t: _PRIORITY.get(t, 100))
        meta = self.git.get_pr_meta(repo, pr_number)
        diff = self.git.get_diff(repo, pr_number)
        results: list[TaskResult] = []
        for name in selected:
            task = TASK_REGISTRY[name]()
            results.append(task.run(self.git, self.llm, repo, pr_number, meta, diff))
        return results
