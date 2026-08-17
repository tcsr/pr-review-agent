from __future__ import annotations

import re

from app.git.base import GitPlatformAdapter
from app.http import build_client, raise_for_status
from app.models import PRMeta, Diff, FileChange, Comment, Verdict, Side

_ISSUE_REF = re.compile(r"#\d+")

_VERDICT_EVENT = {
    Verdict.approve: "APPROVE",
    Verdict.request_changes: "REQUEST_CHANGES",
    Verdict.comment: "COMMENT",
}


class GitHubAdapter(GitPlatformAdapter):
    def __init__(self, repo_owner_name: str, token: str, transport=None,
                 api_base: str = "https://api.github.com"):
        self.repo = repo_owner_name
        self._client = build_client(
            api_base,
            {"Authorization": f"Bearer {token}",
             "Accept": "application/vnd.github+json"},
            transport=transport,
        )

    def _get(self, path: str):
        resp = self._client.get(path)
        raise_for_status(resp)
        return resp.json()

    def _post(self, path: str, payload: dict):
        resp = self._client.post(path, json=payload)
        raise_for_status(resp)
        return resp.json()

    def get_pr_meta(self, repo, pr_number) -> PRMeta:
        pr = self._get(f"/repos/{repo}/pulls/{pr_number}")
        head_sha = pr["head"]["sha"]
        ci_passed = None
        status = self._get(f"/repos/{repo}/commits/{head_sha}/status")
        state = status.get("state")
        if state == "success":
            ci_passed = True
        elif state in ("failure", "error"):
            ci_passed = False
        body = pr.get("body") or ""
        return PRMeta(
            title=pr.get("title") or "",
            body=body,
            author=pr.get("user", {}).get("login", ""),
            base_sha=pr["base"]["sha"],
            head_sha=head_sha,
            labels=[l["name"] for l in pr.get("labels", [])],
            linked_issues=_ISSUE_REF.findall(body),
            ci_passed=ci_passed,
        )

    def get_diff(self, repo, pr_number) -> Diff:
        files = self._get(f"/repos/{repo}/pulls/{pr_number}/files")
        return Diff(files=[
            FileChange(path=f["filename"], patch=f.get("patch") or "",
                       additions=f.get("additions", 0),
                       deletions=f.get("deletions", 0),
                       status=f.get("status", ""))
            for f in files
        ])

    # write methods added in Task 3
    def post_comment(self, repo, pr_number, body) -> str:
        raise NotImplementedError

    def post_inline_comment(self, repo, pr_number, path, line, body, side: Side) -> str:
        raise NotImplementedError

    def set_review_verdict(self, repo, pr_number, verdict: Verdict, body) -> None:
        raise NotImplementedError

    def get_thread(self, repo, pr_number) -> list[Comment]:
        raise NotImplementedError

    def reply(self, repo, pr_number, in_reply_to, body) -> str:
        raise NotImplementedError
