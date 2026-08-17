from app.tasks.code_review import CodeReviewTask
from app.review_context import ReviewContext
from app.git.fake import FakeGitAdapter
from app.llm.fake import FakeLLMAdapter
from tests.fixtures import sample_meta, sample_diff


def _git():
    return FakeGitAdapter(seed={("o/r", 1): (sample_meta(), sample_diff())})


def test_criteria_appear_in_prompt():
    git = _git()
    captured = {}
    def responder(system, msgs):
        captured["p"] = msgs[-1].content
        return "[]"
    llm = FakeLLMAdapter(responder=responder)
    ctx = ReviewContext(review_criteria=["No secrets.", "Docstrings please."],
                        gates={}, stacks=set())
    CodeReviewTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1),
                         git.get_diff("o/r", 1), context=ctx)
    assert "No secrets." in captured["p"]
    assert "Docstrings please." in captured["p"]


def test_runs_without_context():
    git = _git()
    llm = FakeLLMAdapter(responses=["[]"])
    res = CodeReviewTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1),
                               git.get_diff("o/r", 1))
    assert res.name == "code_review"
