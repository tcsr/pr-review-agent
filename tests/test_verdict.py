import json
from app.tasks.verdict import VerdictTask
from app.review_context import ReviewContext
from app.config import GateConfig
from app.models import Verdict
from app.git.fake import FakeGitAdapter
from app.llm.fake import FakeLLMAdapter
from tests.fixtures import sample_meta, sample_diff


def _git(**over):
    return FakeGitAdapter(seed={("o/r", 1): (sample_meta(**over), sample_diff())})


def test_blocking_gate_forces_request_changes_without_llm():
    git = _git(ci_passed=False)
    llm = FakeLLMAdapter(responder=lambda s, m: (_ for _ in ()).throw(AssertionError("LLM must not be called")))
    ctx = ReviewContext(gates={"ci_must_pass": GateConfig(severity="block")})
    res = VerdictTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1),
                            git.get_diff("o/r", 1), context=ctx)
    assert res.posted == 1
    assert git.verdicts[0][0] == Verdict.request_changes


def test_llm_verdict_used_when_no_blocking_failures():
    git = _git()
    llm = FakeLLMAdapter(responses=[json.dumps({"verdict": "approve", "reason": "LGTM"})])
    res = VerdictTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1),
                            git.get_diff("o/r", 1), context=ReviewContext())
    assert git.verdicts[0][0] == Verdict.approve


def test_malformed_llm_defaults_to_comment():
    git = _git()
    llm = FakeLLMAdapter(responses=["not json"])
    VerdictTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1),
                      git.get_diff("o/r", 1), context=ReviewContext())
    assert git.verdicts[0][0] == Verdict.comment
