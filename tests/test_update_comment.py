import httpx
from app.git.github import GitHubAdapter
from app.git.fake import FakeGitAdapter
from app.models import Comment
from tests.fixtures import sample_meta, sample_diff


def test_github_update_comment_patches():
    seen = {}
    def handler(request):
        import json
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": 5})
    a = GitHubAdapter("o/r", "t", transport=httpx.MockTransport(handler))
    a.update_comment("o/r", 1, "5", "new body")
    assert seen["method"] == "PATCH"
    assert seen["path"] == "/repos/o/r/issues/comments/5"
    assert seen["body"]["body"] == "new body"


def test_fake_update_comment_mutates():
    a = FakeGitAdapter(seed={("o/r", 1): (sample_meta(), sample_diff())})
    cid = a.post_comment("o/r", 1, "old")
    a.update_comment("o/r", 1, cid, "new")
    assert a.comments[0].body == "new"
    assert a.updates[0] == (cid, "new")
