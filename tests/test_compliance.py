from app.tasks.compliance import ComplianceTask
from app.review_context import ReviewContext
from app.config import GateConfig
from app.git.fake import FakeGitAdapter
from app.llm.fake import FakeLLMAdapter
from tests.fixtures import sample_meta, sample_diff


def _git(**meta_over):
    return FakeGitAdapter(seed={("o/r", 1): (sample_meta(**meta_over), sample_diff())})


def test_posts_checklist_with_pass_and_fail():
    git = _git(linked_issues=[], ci_passed=False)
    llm = FakeLLMAdapter(responses=[""])
    ctx = ReviewContext(gates={
        "require_linked_issue": GateConfig(severity="warn"),
        "ci_must_pass": GateConfig(severity="block"),
    })
    res = ComplianceTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1),
                               git.get_diff("o/r", 1), context=ctx)
    assert res.posted == 1
    body = git.comments[0].body
    assert "require_linked_issue" in body
    assert "ci_must_pass" in body
    assert "❌" in body  # both fail


def test_no_gates_posts_nothing():
    git = _git()
    llm = FakeLLMAdapter(responses=[""])
    res = ComplianceTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1),
                               git.get_diff("o/r", 1), context=ReviewContext())
    assert res.posted == 0
    assert git.comments == []


def test_no_context_posts_nothing():
    git = _git()
    llm = FakeLLMAdapter(responses=[""])
    res = ComplianceTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1),
                               git.get_diff("o/r", 1))
    assert res.posted == 0
