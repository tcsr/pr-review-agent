import json
import httpx
from app.git.github import GitHubAdapter
from app.git.fake import FakeGitAdapter
from tests.fixtures import sample_meta, sample_diff


def test_github_add_labels():
    seen = {}
    def handler(request):
        assert request.url.path == "/repos/o/r/issues/1/labels"
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=[])
    GitHubAdapter("o/r", "t", transport=httpx.MockTransport(handler)).add_labels("o/r", 1, ["size/S"])
    assert seen["labels"] == ["size/S"]


def test_github_assign_reviewers():
    seen = {}
    def handler(request):
        assert request.url.path == "/repos/o/r/pulls/1/requested_reviewers"
        seen.update(json.loads(request.content))
        return httpx.Response(201, json={})
    GitHubAdapter("o/r", "t", transport=httpx.MockTransport(handler)).assign_reviewers("o/r", 1, ["alice"])
    assert seen["reviewers"] == ["alice"]


def test_fake_records_labels_and_reviewers():
    a = FakeGitAdapter(seed={("o/r", 1): (sample_meta(), sample_diff())})
    a.add_labels("o/r", 1, ["type/fix"])
    a.assign_reviewers("o/r", 1, ["bob"])
    assert a.labels == ["type/fix"]
    assert a.reviewers == ["bob"]
