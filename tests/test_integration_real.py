from __future__ import annotations

import httpx
from app.reviewer import Reviewer
from app.git.github import GitHubAdapter
from app.llm.claude import ClaudeAdapter


def test_reviewer_runs_with_real_adapters_over_mock_http():
    def gh(request):
        p = request.url.path
        if p == "/repos/o/r/pulls/1":
            return httpx.Response(200, json={
                "title": "t", "body": "", "user": {"login": "a"},
                "base": {"sha": "b"}, "head": {"sha": "H"}, "labels": [],
            })
        if p == "/repos/o/r/commits/H/status":
            return httpx.Response(200, json={"state": "success"})
        if p == "/repos/o/r/pulls/1/files":
            return httpx.Response(200, json=[
                {"filename": "app.py", "patch": "@@ +x", "additions": 1,
                 "deletions": 0, "status": "modified"}])
        if p == "/repos/o/r/issues/1/comments":
            return httpx.Response(201, json={"id": 100})
        return httpx.Response(404, text=p)

    def llm(request):
        return httpx.Response(200, json={
            "content": [{"type": "text", "text": "This PR edits app.py."}],
            "usage": {"input_tokens": 5, "output_tokens": 5},
        })

    git = GitHubAdapter("o/r", "tok", transport=httpx.MockTransport(gh))
    claude = ClaudeAdapter("sk", "claude-sonnet-5", transport=httpx.MockTransport(llm))
    results = Reviewer(git, claude).review("o/r", 1, ["summarize"])
    assert [r.name for r in results] == ["summarize"]
    assert results[0].posted == 1
