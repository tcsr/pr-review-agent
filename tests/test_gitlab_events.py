from app.ingress.events import parse_gitlab_event
from app.models import Platform


def test_mr_open_maps():
    payload = {"object_kind": "merge_request",
               "project": {"path_with_namespace": "grp/proj"},
               "object_attributes": {"iid": 7, "action": "open",
                                     "last_commit": {"id": "abc"}}}
    ev = parse_gitlab_event(payload, "Merge Request Hook")
    assert ev.platform == Platform.gitlab
    assert ev.repo == "grp/proj"
    assert ev.pr_number == 7
    assert ev.head_sha == "abc"
    assert ev.action == "open"


def test_mr_close_ignored():
    payload = {"object_attributes": {"iid": 7, "action": "close",
                                     "last_commit": {"id": "abc"}},
               "project": {"path_with_namespace": "grp/proj"}}
    assert parse_gitlab_event(payload, "Merge Request Hook") is None


def test_note_on_mr_maps_comment():
    payload = {"object_kind": "note",
               "project": {"path_with_namespace": "grp/proj"},
               "merge_request": {"iid": 5},
               "user": {"username": "alice"},
               "object_attributes": {"id": 99, "note": "@pr-agent why?"}}
    ev = parse_gitlab_event(payload, "Note Hook")
    assert ev.action == "comment"
    assert ev.pr_number == 5
    assert ev.head_sha == "comment-99"
    assert ev.comment_body == "@pr-agent why?"
    assert ev.comment_author == "alice"


def test_non_mr_event_ignored():
    assert parse_gitlab_event({}, "Push Hook") is None
