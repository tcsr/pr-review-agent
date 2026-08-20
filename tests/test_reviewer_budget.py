from app.reviewer import Reviewer
from app.git.fake import FakeGitAdapter
from app.llm.fake import FakeLLMAdapter
from app.models import PRMeta, Diff, FileChange


def _meta():
    return PRMeta(title="t", body="", author="a", base_sha="b", head_sha="h",
                  labels=[], linked_issues=[], ci_passed=True)


def _big_diff():
    return Diff(files=[
        FileChange(path="a.py", patch="w " * 40, additions=40, deletions=0, status="modified"),
        FileChange(path="b.py", patch="z " * 40, additions=40, deletions=0, status="modified"),
    ])


def _git():
    return FakeGitAdapter(seed={("o/r", 1): (_meta(), _big_diff())})


def test_budget_truncates_and_notes():
    git = _git()
    captured = {}
    def responder(system, msgs):
        captured["prompt"] = msgs[-1].content
        return "[]"
    llm = FakeLLMAdapter(responder=responder)
    # budget fits ~one 40-token file
    Reviewer(git, llm).review("o/r", 1, ["code_review"], max_tokens_per_pr=40, skip_globs=[])
    assert "truncated" in captured["prompt"].lower()


def test_no_budget_no_note():
    git = _git()
    captured = {}
    def responder(system, msgs):
        captured["prompt"] = msgs[-1].content
        return "[]"
    llm = FakeLLMAdapter(responder=responder)
    Reviewer(git, llm).review("o/r", 1, ["code_review"])  # no budget
    assert "truncated" not in captured["prompt"].lower()
