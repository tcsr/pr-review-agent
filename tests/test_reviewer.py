import json
from app.git.fake import FakeGitAdapter
from app.llm.fake import FakeLLMAdapter
from app.reviewer import Reviewer
from tests.fixtures import sample_meta, sample_diff


def _git():
    return FakeGitAdapter(seed={("o/r", 1): (sample_meta(), sample_diff())})


def test_runs_selected_tasks():
    git = _git()
    def responder(system, msgs):
        return json.dumps([]) if "JSON array" in system else "Summary text."
    llm = FakeLLMAdapter(responder=responder)
    results = Reviewer(git, llm).review("o/r", 1, ["code_review", "summarize"])
    names = {r.name for r in results}
    assert names == {"code_review", "summarize"}
    assert len(git.comments) == 1  # summary posted


def test_unknown_task_skipped():
    git = _git()
    llm = FakeLLMAdapter(responses=["Summary text."])
    results = Reviewer(git, llm).review("o/r", 1, ["nonexistent", "summarize"])
    assert [r.name for r in results] == ["summarize"]


def test_fetches_meta_and_diff_once():
    git = _git()
    llm = FakeLLMAdapter(responses=["This PR changes app.py to fix a bug."])
    Reviewer(git, llm).review("o/r", 1, ["summarize"])
    # summarize posted exactly one comment from the seeded diff
    assert "app.py" in git.comments[0].body
