import httpx
from app.git.github import GitHubAdapter
from app.models import Verdict, Side


def _adapter(handler):
    return GitHubAdapter("o/r", "tok", transport=httpx.MockTransport(handler))


def test_post_comment_returns_id():
    def handler(request):
        assert request.url.path == "/repos/o/r/issues/1/comments"
        assert request.method == "POST"
        return httpx.Response(201, json={"id": 555})
    assert _adapter(handler).post_comment("o/r", 1, "hi") == "555"


def test_post_inline_comment_sends_commit_and_side():
    seen = {}
    def handler(request):
        import json
        if request.url.path == "/repos/o/r/pulls/1":
            return httpx.Response(200, json={
                "title": "t", "body": "", "user": {"login": "a"},
                "base": {"sha": "b"}, "head": {"sha": "HEADSHA"}, "labels": [],
            })
        if request.url.path == "/repos/o/r/commits/HEADSHA/status":
            return httpx.Response(200, json={"state": "pending"})
        if request.url.path == "/repos/o/r/pulls/1/comments":
            seen.update(json.loads(request.content))
            return httpx.Response(201, json={"id": 9})
        return httpx.Response(404, text="x")
    cid = _adapter(handler).post_inline_comment("o/r", 1, "a.py", 3, "nit", Side.right)
    assert cid == "9"
    assert seen["commit_id"] == "HEADSHA"
    assert seen["side"] == "RIGHT"
    assert seen["path"] == "a.py" and seen["line"] == 3


def test_set_review_verdict_maps_event():
    seen = {}
    def handler(request):
        import json
        assert request.url.path == "/repos/o/r/pulls/1/reviews"
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"id": 1})
    _adapter(handler).set_review_verdict("o/r", 1, Verdict.request_changes, "please fix")
    assert seen["event"] == "REQUEST_CHANGES"
    assert seen["body"] == "please fix"


def test_get_thread_maps_comments():
    def handler(request):
        assert request.url.path == "/repos/o/r/issues/1/comments"
        return httpx.Response(200, json=[
            {"id": 1, "user": {"login": "bob"}, "body": "hello"},
        ])
    thread = _adapter(handler).get_thread("o/r", 1)
    assert thread[0].author == "bob"
    assert thread[0].id == "1"


def test_inline_comments_fetch_head_sha_once():
    calls = {"pulls": 0}
    def handler(request):
        import json
        p = request.url.path
        if p == "/repos/o/r/pulls/1":
            calls["pulls"] += 1
            return httpx.Response(200, json={
                "title": "t", "body": "", "user": {"login": "a"},
                "base": {"sha": "b"}, "head": {"sha": "H"}, "labels": []})
        if p == "/repos/o/r/commits/H/status":
            return httpx.Response(200, json={"state": "pending"})
        if p == "/repos/o/r/pulls/1/comments":
            return httpx.Response(201, json={"id": 1})
        return httpx.Response(404, text=p)
    a = _adapter(handler)
    a.post_inline_comment("o/r", 1, "a.py", 1, "x", Side.right)
    a.post_inline_comment("o/r", 1, "a.py", 2, "y", Side.right)
    assert calls["pulls"] == 1
