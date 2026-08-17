import httpx
from app.git.github import GitHubAdapter


def _adapter(handler):
    return GitHubAdapter("o/r", "tok", transport=httpx.MockTransport(handler))


def test_get_pr_meta_maps_fields():
    def handler(request):
        if request.url.path == "/repos/o/r/pulls/1":
            return httpx.Response(200, json={
                "title": "Add x", "body": "Fixes #7",
                "user": {"login": "alice"},
                "base": {"sha": "b1"}, "head": {"sha": "h1"},
                "labels": [{"name": "bug"}],
            })
        if request.url.path == "/repos/o/r/commits/h1/status":
            return httpx.Response(200, json={"state": "success"})
        return httpx.Response(404, text="nope")

    meta = _adapter(handler).get_pr_meta("o/r", 1)
    assert meta.title == "Add x"
    assert meta.author == "alice"
    assert meta.head_sha == "h1"
    assert meta.labels == ["bug"]
    assert meta.linked_issues == ["#7"]
    assert meta.ci_passed is True


def test_get_diff_maps_files():
    def handler(request):
        assert request.url.path == "/repos/o/r/pulls/1/files"
        return httpx.Response(200, json=[
            {"filename": "a.py", "patch": "@@ -1 +1 @@", "additions": 2,
             "deletions": 1, "status": "modified"},
        ])

    diff = _adapter(handler).get_diff("o/r", 1)
    assert len(diff.files) == 1
    assert diff.files[0].path == "a.py"
    assert diff.total_changed_lines() == 3


def test_get_diff_handles_missing_patch():
    def handler(request):
        return httpx.Response(200, json=[
            {"filename": "bin.dat", "additions": 0, "deletions": 0, "status": "added"},
        ])
    diff = _adapter(handler).get_diff("o/r", 1)
    assert diff.files[0].patch == ""
