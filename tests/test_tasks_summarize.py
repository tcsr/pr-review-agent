from app.git.fake import FakeGitAdapter
from app.llm.fake import FakeLLMAdapter
from app.tasks.summarize import SummarizeTask
from tests.fixtures import sample_meta, sample_diff


def _git():
    return FakeGitAdapter(seed={("o/r", 1): (sample_meta(), sample_diff())})


def test_posts_single_summary_comment():
    git = _git()
    llm = FakeLLMAdapter(responses=["This PR changes app.py to fix a bug."])
    res = SummarizeTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1), git.get_diff("o/r", 1))
    assert res.posted == 1
    assert len(git.comments) == 1
    assert "app.py" in git.comments[0].body


def test_empty_response_posts_nothing():
    git = _git()
    llm = FakeLLMAdapter(responses=["   "])
    res = SummarizeTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1), git.get_diff("o/r", 1))
    assert res.posted == 0
    assert git.comments == []
