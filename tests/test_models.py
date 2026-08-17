from app.models import Platform, Verdict, Side, FileChange, Diff, PRMeta, PR, Comment, Event


def test_enums():
    assert Platform.github == "github"
    assert Verdict.request_changes == "request_changes"
    assert Side.right == "right"


def test_diff_total_changed_lines():
    diff = Diff(files=[
        FileChange(path="a.py", patch="@@", additions=3, deletions=1, status="modified"),
        FileChange(path="b.py", patch="@@", additions=5, deletions=0, status="added"),
    ])
    assert diff.total_changed_lines() == 9


def test_event_defaults():
    ev = Event(platform=Platform.github, repo="o/r", pr_number=1, head_sha="abc", action="opened")
    assert ev.comment_body is None
