from __future__ import annotations

import re

from app.git.base import GitPlatformAdapter
from app.http import build_client, raise_for_status
from app.models import PRMeta, Diff, FileChange, Comment, Verdict, Side, PR, Platform

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
        self._head_sha_cache: dict[tuple[str, int], str] = {}

    def _get(self, path: str):
        resp = self._client.get(path)
        raise_for_status(resp)
        return resp.json()

    def _post(self, path: str, payload: dict):
        resp = self._client.post(path, json=payload)
        raise_for_status(resp)
        return resp.json()

    def _head_sha(self, repo, pr_number) -> str:
        key = (repo, pr_number)
        if key not in self._head_sha_cache:
            self._head_sha_cache[key] = self.get_pr_meta(repo, pr_number).head_sha
        return self._head_sha_cache[key]

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
        r = self._post(f"/repos/{repo}/issues/{pr_number}/comments", {"body": body})
        return str(r["id"])

    def post_inline_comment(self, repo, pr_number, path, line, body, side: Side) -> str:
        commit_id = self._head_sha(repo, pr_number)
        r = self._post(f"/repos/{repo}/pulls/{pr_number}/comments", {
            "body": body, "path": path, "line": line,
            "side": side.name.upper(), "commit_id": commit_id,
        })
        return str(r["id"])

    def set_review_verdict(self, repo, pr_number, verdict: Verdict, body) -> None:
        self._post(f"/repos/{repo}/pulls/{pr_number}/reviews",
                   {"event": _VERDICT_EVENT[verdict], "body": body})

    def get_thread(self, repo, pr_number) -> list[Comment]:
        rows = self._get(f"/repos/{repo}/issues/{pr_number}/comments")
        return [Comment(id=str(c["id"]), author=c.get("user", {}).get("login", ""),
                        body=c.get("body", "")) for c in rows]

    def reply(self, repo, pr_number, in_reply_to, body) -> str:
        # GitHub issue comments are not natively threaded; in_reply_to is accepted for interface conformance but not sent.
        r = self._post(f"/repos/{repo}/issues/{pr_number}/comments", {"body": body})
        return str(r["id"])

    def list_open_prs(self, repo) -> list[PR]:
        rows = self._get(f"/repos/{repo}/pulls?state=open")
        return [PR(platform=Platform.github, repo=repo, number=r["number"],
                   head_sha=r["head"]["sha"]) for r in rows]

    def add_labels(self, repo, pr_number, labels) -> None:
        self._post(f"/repos/{repo}/issues/{pr_number}/labels", {"labels": labels})

    def assign_reviewers(self, repo, pr_number, reviewers) -> None:
        self._post(f"/repos/{repo}/pulls/{pr_number}/requested_reviewers",
                   {"reviewers": reviewers})

    def update_comment(self, repo, pr_number, comment_id, body) -> None:
        resp = self._client.patch(
            f"/repos/{repo}/issues/comments/{comment_id}", json={"body": body})
        raise_for_status(resp)
