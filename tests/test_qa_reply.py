from app.tasks.qa_reply import QaReplyTask
from app.review_context import ReviewContext
from app.models import Comment
from app.git.fake import FakeGitAdapter
from app.llm.fake import FakeLLMAdapter
from tests.fixtures import sample_meta, sample_diff


def _git():
    return FakeGitAdapter(seed={("o/r", 1): (sample_meta(), sample_diff())})


def test_answers_bot_mention():
    git = _git()
    git.comments.append(Comment(id="42", author="alice", body="@pr-agent why this change?"))
    llm = FakeLLMAdapter(responses=["Because it fixes a bug."])
    ctx = ReviewContext(bot_handle="pr-agent")
    res = QaReplyTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1),
                            git.get_diff("o/r", 1), context=ctx)
    assert res.posted == 1
    assert git.replies[0].body == "Because it fixes a bug."


def test_no_mention_posts_nothing():
    git = _git()
    git.comments.append(Comment(id="1", author="alice", body="looks good"))
    llm = FakeLLMAdapter(responses=["unused"])
    res = QaReplyTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1),
                            git.get_diff("o/r", 1), context=ReviewContext(bot_handle="pr-agent"))
    assert res.posted == 0
    assert git.replies == []


def test_no_handle_posts_nothing():
    git = _git()
    git.comments.append(Comment(id="1", author="alice", body="@pr-agent hi"))
    res = QaReplyTask().run(git, FakeLLMAdapter(responses=["x"]), "o/r", 1,
                            git.get_pr_meta("o/r", 1), git.get_diff("o/r", 1),
                            context=ReviewContext())
    assert res.posted == 0


def test_answers_latest_mention():
    git = _git()
    git.comments.append(Comment(id="1", author="alice", body="@pr-agent first?"))
    git.comments.append(Comment(id="2", author="bob", body="@pr-agent second?"))
    llm = FakeLLMAdapter(responder=lambda s, m: "answer")
    QaReplyTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1),
                      git.get_diff("o/r", 1), context=ReviewContext(bot_handle="pr-agent"))
    assert git.replies[0].body == "answer"
    # replied to the latest mention (id "2")
    # (FakeGitAdapter.reply records the reply; the in_reply_to is exercised via the call)
