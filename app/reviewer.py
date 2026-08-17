from __future__ import annotations

from app.review_context import ReviewContext
from app.tasks.base import Task, TaskResult
from app.tasks.code_review import CodeReviewTask
from app.tasks.suggest_fixes import SuggestFixesTask
from app.tasks.summarize import SummarizeTask
from app.tasks.compliance import ComplianceTask
from app.tasks.verdict import VerdictTask
from app.tasks.triage import TriageTask
from app.tasks.qa_reply import QaReplyTask
from app.config import StacksConfig
from app.stack.detect import detect_stacks
from app.stack.packs import pack_criteria
from app.redact import redact_diff

TASK_REGISTRY: dict[str, type[Task]] = {
    "triage": TriageTask,
    "code_review": CodeReviewTask,
    "suggest_fixes": SuggestFixesTask,
    "summarize": SummarizeTask,
    "compliance": ComplianceTask,
    "verdict": VerdictTask,
    "qa_reply": QaReplyTask,
}

# Lower number runs earlier. code_review before verdict (verdict added later).
_PRIORITY = {"triage": 1, "code_review": 0, "suggest_fixes": 3, "summarize": 5, "compliance": 7, "verdict": 9, "qa_reply": 4}


class Reviewer:
    def __init__(self, git, llm):
        self.git = git
        self.llm = llm

    def review(self, repo: str, pr_number: int, tasks: list[str], rules=None, stacks_cfg=None, bot_handle="") -> list[TaskResult]:
        selected = [t for t in tasks if t in TASK_REGISTRY]
        selected.sort(key=lambda t: _PRIORITY.get(t, 100))
        meta = self.git.get_pr_meta(repo, pr_number)
        diff = redact_diff(self.git.get_diff(repo, pr_number))
        stacks = detect_stacks(diff)
        criteria = (list(rules.review_criteria) if rules else [])
        criteria += pack_criteria(stacks, stacks_cfg or StacksConfig())
        gates = rules.gates if rules else {}
        context = ReviewContext(review_criteria=criteria, gates=gates, stacks=stacks,
                                bot_handle=bot_handle)
        results: list[TaskResult] = []
        for name in selected:
            task = TASK_REGISTRY[name]()
            results.append(task.run(self.git, self.llm, repo, pr_number, meta, diff,
                                    context=context))
        return results
