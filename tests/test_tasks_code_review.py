import json
from app.git.fake import FakeGitAdapter
from app.llm.fake import FakeLLMAdapter
from app.tasks.code_review import CodeReviewTask
from tests.fixtures import sample_meta, sample_diff


def _git():
    return FakeGitAdapter(seed={("o/r", 1): (sample_meta(), sample_diff())})


def test_posts_one_inline_comment_per_finding():
    findings = json.dumps([
        {"path": "src/app.py", "line": 1, "comment": "Use a constant."},
        {"path": "src/app.py", "line": 2, "comment": "Missing docstring."},
    ])
    git = _git()
    llm = FakeLLMAdapter(responses=[findings])
    res = CodeReviewTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1), git.get_diff("o/r", 1))
    assert res.posted == 2
    assert len(git.inline_comments) == 2
    assert git.inline_comments[0].body == "Use a constant."


def test_malformed_json_posts_nothing():
    git = _git()
    llm = FakeLLMAdapter(responses=["not json"])
    res = CodeReviewTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1), git.get_diff("o/r", 1))
    assert res.posted == 0
    assert git.inline_comments == []


def test_prompt_includes_diff_patch():
    git = _git()
    llm = FakeLLMAdapter(responses=["[]"])
    CodeReviewTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1), git.get_diff("o/r", 1))
    system, messages = llm.calls[0]
    assert "src/app.py" in messages[-1].content


def test_finding_missing_key_is_skipped():
    git = _git()
    llm = FakeLLMAdapter(responses=[json.dumps([{"path": "src/app.py", "line": 1}])])  # no "comment"
    res = CodeReviewTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1), git.get_diff("o/r", 1))
    assert res.posted == 0
    assert git.inline_comments == []
