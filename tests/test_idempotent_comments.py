from app.tasks.comments import post_or_update
from app.tasks.summarize import SummarizeTask
from app.git.fake import FakeGitAdapter
from app.llm.fake import FakeLLMAdapter
from tests.fixtures import sample_meta, sample_diff


def _git():
    return FakeGitAdapter(seed={("o/r", 1): (sample_meta(), sample_diff())})


def test_post_or_update_posts_then_updates():
    git = _git()
    first = post_or_update(git, "o/r", 1, "pr-agent:x", "first body")
    assert len(git.comments) == 1
    assert "<!-- pr-agent:x -->" in git.comments[0].body
    second = post_or_update(git, "o/r", 1, "pr-agent:x", "second body")
    assert second == first             # same comment
    assert len(git.comments) == 1      # not duplicated
    assert "second body" in git.comments[0].body
    assert len(git.updates) == 1


def test_summarize_is_idempotent_on_rerun():
    git = _git()
    llm = FakeLLMAdapter(responses=["A summary."])
    SummarizeTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1), git.get_diff("o/r", 1))
    llm2 = FakeLLMAdapter(responses=["A summary."])
    SummarizeTask().run(git, llm2, "o/r", 1, git.get_pr_meta("o/r", 1), git.get_diff("o/r", 1))
    assert len(git.comments) == 1      # re-run edited, not stacked
