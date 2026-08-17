import httpx
from app.git.github import GitHubAdapter
from app.git.fake import FakeGitAdapter
from app.models import Platform
from tests.fixtures import sample_meta, sample_diff


def test_github_list_open_prs():
    def handler(request):
        assert request.url.path == "/repos/o/r/pulls"
        assert request.url.params.get("state") == "open"
        return httpx.Response(200, json=[
            {"number": 1, "head": {"sha": "s1"}},
            {"number": 2, "head": {"sha": "s2"}},
        ])
    a = GitHubAdapter("o/r", "t", transport=httpx.MockTransport(handler))
    prs = a.list_open_prs("o/r")
    assert [p.number for p in prs] == [1, 2]
    assert prs[0].platform == Platform.github
    assert prs[1].head_sha == "s2"


def test_fake_list_open_prs():
    a = FakeGitAdapter(seed={("o/r", 1): (sample_meta(head_sha="H1"), sample_diff())})
    prs = a.list_open_prs("o/r")
    assert len(prs) == 1
    assert prs[0].number == 1
    assert prs[0].head_sha == "H1"
