from app.config import load_settings, Settings, LLMConfig, StoreConfig
from app.review_context import ReviewContext
from app.reviewer import Reviewer
from app.git.fake import FakeGitAdapter
from app.llm.fake import FakeLLMAdapter
from tests.fixtures import sample_meta, sample_diff


def _write(tmp_path, text):
    p = tmp_path / "config.yaml"
    p.write_text(text)
    return str(p)


def test_settings_bot_handle_default_and_load(tmp_path):
    path = _write(tmp_path, """
llm: {provider: fake, model: fake}
store: {url: 'sqlite:///:memory:'}
defaults: {tasks: [code_review]}
bot_handle: pr-agent
repos: []
""")
    assert load_settings(path, env={}).bot_handle == "pr-agent"


def test_review_context_carries_bot_handle():
    ctx = ReviewContext(bot_handle="pr-agent")
    assert ctx.bot_handle == "pr-agent"


def test_reviewer_threads_bot_handle_into_context():
    git = FakeGitAdapter(seed={("o/r", 1): (sample_meta(), sample_diff())})
    captured = {}

    class _Probe:
        name = "code_review"
        def run(self, g, l, repo, pr, meta, diff, context=None):
            captured["handle"] = context.bot_handle
            from app.tasks.base import TaskResult
            return TaskResult("code_review", 0)

    from app import reviewer as rv
    rv.TASK_REGISTRY["_probe"] = _Probe
    try:
        Reviewer(git, FakeLLMAdapter(responses=[""])).review(
            "o/r", 1, ["_probe"], bot_handle="pr-agent")
        assert captured["handle"] == "pr-agent"
    finally:
        del rv.TASK_REGISTRY["_probe"]
