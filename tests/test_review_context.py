from app.review_context import ReviewContext
from app.reviewer import Reviewer
from app.git.fake import FakeGitAdapter
from app.llm.fake import FakeLLMAdapter
from app.config import RulesConfig, StacksConfig
from tests.fixtures import sample_meta, sample_diff


def _git():
    return FakeGitAdapter(seed={("o/r", 1): (sample_meta(), sample_diff())})


def test_review_context_dataclass():
    ctx = ReviewContext(review_criteria=["x"], gates={}, stacks={"python"})
    assert ctx.review_criteria == ["x"]
    assert ctx.stacks == {"python"}


def test_reviewer_passes_criteria_including_pack(monkeypatch):
    # sample_diff has src/app.py -> python stack -> python pack criteria present
    git = _git()
    captured = {}
    def responder(system, msgs):
        captured["prompt"] = msgs[-1].content
        return "[]"
    llm = FakeLLMAdapter(responder=responder)
    rules = RulesConfig(review_criteria=["Custom: no TODOs."])
    Reviewer(git, llm).review("o/r", 1, ["code_review"], rules=rules,
                              stacks_cfg=StacksConfig())
    assert "Custom: no TODOs." in captured["prompt"]
    assert "type hints" in captured["prompt"].lower()  # from python pack
