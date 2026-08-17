from app.git.fake import FakeGitAdapter
from app.models import Verdict, Side
from tests.fixtures import sample_meta, sample_diff


def _adapter():
    return FakeGitAdapter(seed={("o/r", 1): (sample_meta(), sample_diff())})


def test_get_meta_and_diff():
    a = _adapter()
    assert a.get_pr_meta("o/r", 1).author == "alice"
    assert a.get_diff("o/r", 1).total_changed_lines() == 2


def test_records_comments_and_verdict():
    a = _adapter()
    cid = a.post_comment("o/r", 1, "hello")
    a.post_inline_comment("o/r", 1, "src/app.py", 1, "nit", Side.right)
    a.set_review_verdict("o/r", 1, Verdict.approve, "LGTM")
    assert a.comments[0].body == "hello"
    assert cid == a.comments[0].id
    assert a.inline_comments[0].path == "src/app.py"
    assert a.verdicts[0] == (Verdict.approve, "LGTM")
