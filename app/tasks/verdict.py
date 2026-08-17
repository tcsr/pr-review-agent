from __future__ import annotations

import json

from app.llm.base import Message
from app.models import Verdict
from app.rules.gates import evaluate_gates
from app.tasks.base import Task, TaskResult
from app.tasks.code_review import _render_diff

_SYSTEM = (
    'You are a PR gatekeeper. Respond ONLY with JSON '
    '{"verdict": "approve|request_changes|comment", "reason": str}.'
)
_MAP = {
    "approve": Verdict.approve,
    "request_changes": Verdict.request_changes,
    "comment": Verdict.comment,
}


class VerdictTask(Task):
    name = "verdict"

    def run(self, git, llm, repo, pr_number, meta, diff, context=None) -> TaskResult:
        gates = context.gates if context else {}
        results = evaluate_gates(meta, diff, gates)
        blocking = [r for r in results if not r.passed and r.severity == "block"]
        if blocking:
            body = "Blocking gate failures:\n" + "\n".join(
                f"- {r.name}: {r.message}" for r in blocking)
            git.set_review_verdict(repo, pr_number, Verdict.request_changes, body)
            return TaskResult(self.name, 1)

        prompt = f"PR title: {meta.title}\n\nDiff:\n{_render_diff(diff)}\n\nGive your verdict."
        resp = llm.complete(_SYSTEM, [Message(role="user", content=prompt)], max_tokens=500)
        verdict, reason = Verdict.comment, ""
        try:
            data = json.loads(resp.text)
            verdict = _MAP.get(data.get("verdict"), Verdict.comment)
            reason = data.get("reason", "")
        except (json.JSONDecodeError, AttributeError):
            pass
        git.set_review_verdict(repo, pr_number, verdict, reason)
        return TaskResult(self.name, 1)
