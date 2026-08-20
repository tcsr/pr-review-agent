import httpx
from app.git.gitlab import GitLabAdapter
from app.models import Platform


def _adapter(handler):
    return GitLabAdapter("grp/proj", "tok", transport=httpx.MockTransport(handler))


def test_get_pr_meta_maps_fields():
    def handler(request):
        assert str(request.url) == "https://gitlab.com/api/v4/projects/grp%2Fproj/merge_requests/3"
        assert request.headers["private-token"] == "tok"
        return httpx.Response(200, json={
            "title": "Add x", "description": "Fixes #4",
            "author": {"username": "alice"},
            "sha": "head1", "diff_refs": {"base_sha": "base1"},
            "labels": ["bug"], "head_pipeline": {"status": "success"},
        })
    meta = _adapter(handler).get_pr_meta("grp/proj", 3)
    assert meta.title == "Add x"
    assert meta.author == "alice"
    assert meta.head_sha == "head1"
    assert meta.base_sha == "base1"
    assert meta.labels == ["bug"]
    assert meta.linked_issues == ["#4"]
    assert meta.ci_passed is True


def test_get_diff_counts_lines():
    def handler(request):
        assert str(request.url) == "https://gitlab.com/api/v4/projects/grp%2Fproj/merge_requests/3/changes"
        return httpx.Response(200, json={"changes": [
            {"new_path": "a.py", "diff": "@@\n+added1\n+added2\n-removed1",
             "new_file": False, "deleted_file": False},
        ]})
    diff = _adapter(handler).get_diff("grp/proj", 3)
    assert diff.files[0].path == "a.py"
    assert diff.files[0].additions == 2
    assert diff.files[0].deletions == 1
    assert diff.files[0].status == "modified"


def test_get_diff_new_file_status():
    def handler(request):
        return httpx.Response(200, json={"changes": [
            {"new_path": "n.py", "diff": "+x", "new_file": True, "deleted_file": False},
        ]})
    assert _adapter(handler).get_diff("grp/proj", 3).files[0].status == "added"
