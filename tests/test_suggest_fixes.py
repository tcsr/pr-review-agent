import json
from app.tasks.suggest_fixes import SuggestFixesTask
from app.git.fake import FakeGitAdapter
from app.llm.fake import FakeLLMAdapter
from tests.fixtures import sample_meta, sample_diff


def _git():
    return FakeGitAdapter(seed={("o/r", 1): (sample_meta(), sample_diff())})


def test_posts_suggestion_block():
    git = _git()
    findings = json.dumps([{"path": "src/app.py", "line": 1,
                            "comment": "Rename for clarity.", "suggestion": "new_value = 1"}])
    llm = FakeLLMAdapter(responses=[findings])
    res = SuggestFixesTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1),
                                 git.get_diff("o/r", 1))
    assert res.posted == 1
    body = git.inline_comments[0].body
    assert "```suggestion" in body
    assert "new_value = 1" in body


def test_malformed_posts_nothing():
    git = _git()
    llm = FakeLLMAdapter(responses=["not json"])
    res = SuggestFixesTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1),
                                 git.get_diff("o/r", 1))
    assert res.posted == 0


def test_finding_missing_key_skipped():
    git = _git()
    llm = FakeLLMAdapter(responses=[json.dumps([{"path": "a", "line": 1}])])  # no suggestion
    res = SuggestFixesTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1),
                                 git.get_diff("o/r", 1))
    assert res.posted == 0
