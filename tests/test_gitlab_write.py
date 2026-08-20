import httpx
from app.git.gitlab import GitLabAdapter
from app.models import Verdict, Side, Platform


def _adapter(handler):
    return GitLabAdapter("grp/proj", "tok", transport=httpx.MockTransport(handler))


def test_post_comment_returns_id():
    def handler(request):
        assert request.url.path.endswith("/projects/grp/proj/merge_requests/3/notes")
        assert request.method == "POST"
        return httpx.Response(201, json={"id": 88})
    assert _adapter(handler).post_comment("grp/proj", 3, "hi") == "88"


def test_inline_comment_prefixes_location():
    seen = {}
    def handler(request):
        import json
        seen.update(json.loads(request.content))
        return httpx.Response(201, json={"id": 9})
    _adapter(handler).post_inline_comment("grp/proj", 3, "a.py", 12, "nit", Side.right)
    assert "a.py:12" in seen["body"]
    assert "nit" in seen["body"]


def test_verdict_approve_hits_approve_endpoint():
    seen = {}
    def handler(request):
        seen["path"] = request.url.path
        return httpx.Response(200, json={})
    _adapter(handler).set_review_verdict("grp/proj", 3, Verdict.approve, "LGTM")
    assert seen["path"].endswith("/merge_requests/3/approve")


def test_verdict_request_changes_posts_note():
    seen = {}
    def handler(request):
        import json
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)["body"]
        return httpx.Response(201, json={"id": 1})
    _adapter(handler).set_review_verdict("grp/proj", 3, Verdict.request_changes, "fix")
    assert seen["path"].endswith("/notes")
    assert seen["body"] == "fix"


def test_get_thread_maps_notes():
    def handler(request):
        return httpx.Response(200, json=[
            {"id": 1, "author": {"username": "bob"}, "body": "hello"}])
    t = _adapter(handler).get_thread("grp/proj", 3)
    assert t[0].author == "bob" and t[0].id == "1"


def test_update_comment_puts():
    seen = {}
    def handler(request):
        seen["method"] = request.method
        seen["path"] = request.url.path
        return httpx.Response(200, json={"id": 5})
    _adapter(handler).update_comment("grp/proj", 3, "5", "new")
    assert seen["method"] == "PUT"
    assert seen["path"].endswith("/projects/grp/proj/merge_requests/3/notes/5")


def test_list_open_prs():
    def handler(request):
        assert request.url.params.get("state") == "opened"
        return httpx.Response(200, json=[{"iid": 7, "sha": "s7"}])
    prs = _adapter(handler).list_open_prs("grp/proj")
    assert prs[0].number == 7 and prs[0].head_sha == "s7"
    assert prs[0].platform == Platform.gitlab
