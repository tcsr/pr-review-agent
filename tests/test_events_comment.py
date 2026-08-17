from app.ingress.events import parse_github_event
from app.models import Platform


def _comment_payload(action="created", is_pr=True, body="@pr-agent why?"):
    issue = {"number": 5}
    if is_pr:
        issue["pull_request"] = {"url": "..."}
    return {
        "action": action,
        "repository": {"full_name": "o/r"},
        "issue": issue,
        "comment": {"id": 999, "body": body, "user": {"login": "alice"}},
    }


def test_pr_comment_created_maps_to_event():
    ev = parse_github_event(_comment_payload(), "issue_comment")
    assert ev.platform == Platform.github
    assert ev.repo == "o/r"
    assert ev.pr_number == 5
    assert ev.action == "comment"
    assert ev.comment_body == "@pr-agent why?"
    assert ev.head_sha == "comment-999"


def test_non_pr_issue_comment_ignored():
    assert parse_github_event(_comment_payload(is_pr=False), "issue_comment") is None


def test_deleted_comment_ignored():
    assert parse_github_event(_comment_payload(action="deleted"), "issue_comment") is None
