from app.ingress.events import parse_github_event
from app.models import Platform


def _payload(action="opened"):
    return {
        "action": action,
        "repository": {"full_name": "o/r"},
        "pull_request": {"number": 7, "head": {"sha": "abc"}},
    }


def test_opened_pull_request_maps_to_event():
    ev = parse_github_event(_payload("opened"), "pull_request")
    assert ev.platform == Platform.github
    assert ev.repo == "o/r"
    assert ev.pr_number == 7
    assert ev.head_sha == "abc"
    assert ev.action == "opened"


def test_synchronize_is_accepted():
    assert parse_github_event(_payload("synchronize"), "pull_request") is not None


def test_closed_action_ignored():
    assert parse_github_event(_payload("closed"), "pull_request") is None


def test_non_pr_event_ignored():
    assert parse_github_event(_payload(), "issues") is None
