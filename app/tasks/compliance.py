from __future__ import annotations

from app.rules.gates import evaluate_gates
from app.tasks.base import Task, TaskResult
from app.tasks.comments import post_or_update


class ComplianceTask(Task):
    name = "compliance"

    def run(self, git, llm, repo, pr_number, meta, diff, context=None) -> TaskResult:
        if context is None or not context.gates:
            return TaskResult(self.name, 0)
        results = evaluate_gates(meta, diff, context.gates)
        if not results:
            return TaskResult(self.name, 0)
        lines = ["### Compliance checklist", ""]
        for r in results:
            mark = "✅" if r.passed else "❌"
            lines.append(f"- {mark} **{r.name}** ({r.severity}): {r.message}")
        post_or_update(git, repo, pr_number, "pr-agent:compliance", "\n".join(lines))
        return TaskResult(self.name, 1)
