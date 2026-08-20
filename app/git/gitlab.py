from __future__ import annotations

import re
import urllib.parse

from app.git.base import GitPlatformAdapter
from app.http import build_client, raise_for_status
from app.models import PRMeta, Diff, FileChange, Comment, Verdict, Side, PR, Platform

_ISSUE_REF = re.compile(r"#\d+")


def _count_diff(diff_text: str) -> tuple[int, int]:
    adds = dels = 0
    for line in (diff_text or "").splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            adds += 1
        elif line.startswith("-") and not line.startswith("---"):
            dels += 1
    return adds, dels


class GitLabAdapter(GitPlatformAdapter):
    def __init__(self, project_path: str, token: str, transport=None,
                 api_base: str = "https://gitlab.com/api/v4"):
        self.repo = project_path
        self._client = build_client(api_base, {"PRIVATE-TOKEN": token},
                                    transport=transport)

    def _enc(self, repo: str) -> str:
        return urllib.parse.quote(repo, safe="")

    def _mr(self, repo: str, iid: int) -> str:
        return f"/projects/{self._enc(repo)}/merge_requests/{iid}"

    def _get(self, path: str):
        resp = self._client.get(path)
        raise_for_status(resp)
        return resp.json()

    def _post(self, path: str, payload: dict):
        resp = self._client.post(path, json=payload)
        raise_for_status(resp)
        return resp.json()

    def get_pr_meta(self, repo, pr_number) -> PRMeta:
        d = self._get(self._mr(repo, pr_number))
        status = (d.get("head_pipeline") or {}).get("status")
        ci_passed = True if status == "success" else (
            False if status in ("failed", "canceled") else None)
        body = d.get("description") or ""
        return PRMeta(
            title=d.get("title") or "",
            body=body,
            author=d.get("author", {}).get("username", ""),
            base_sha=(d.get("diff_refs") or {}).get("base_sha", ""),
            head_sha=d.get("sha", ""),
            labels=list(d.get("labels", [])),
            linked_issues=_ISSUE_REF.findall(body),
            ci_passed=ci_passed,
        )

    def get_diff(self, repo, pr_number) -> Diff:
        d = self._get(self._mr(repo, pr_number) + "/changes")
        files = []
        for c in d.get("changes", []):
            adds, dels = _count_diff(c.get("diff", ""))
            status = ("added" if c.get("new_file") else
                      "deleted" if c.get("deleted_file") else "modified")
            files.append(FileChange(path=c["new_path"], patch=c.get("diff", ""),
                                    additions=adds, deletions=dels, status=status))
        return Diff(files=files)

    # write methods (Task 2)
    def post_comment(self, repo, pr_number, body) -> str:
        r = self._post(self._mr(repo, pr_number) + "/notes", {"body": body})
        return str(r["id"])

    def post_inline_comment(self, repo, pr_number, path, line, body, side: Side) -> str:
        r = self._post(self._mr(repo, pr_number) + "/notes",
                       {"body": f"`{path}:{line}` {body}"})
        return str(r["id"])

    def set_review_verdict(self, repo, pr_number, verdict: Verdict, body) -> None:
        if verdict == Verdict.approve:
            self._post(self._mr(repo, pr_number) + "/approve", {})
        else:
            self._post(self._mr(repo, pr_number) + "/notes", {"body": body})

    def get_thread(self, repo, pr_number) -> list[Comment]:
        rows = self._get(self._mr(repo, pr_number) + "/notes")
        return [Comment(id=str(c["id"]), author=c.get("author", {}).get("username", ""),
                        body=c.get("body", "")) for c in rows]

    def reply(self, repo, pr_number, in_reply_to, body) -> str:
        r = self._post(self._mr(repo, pr_number) + "/notes", {"body": body})
        return str(r["id"])

    def update_comment(self, repo, pr_number, comment_id, body) -> None:
        resp = self._client.put(self._mr(repo, pr_number) + f"/notes/{comment_id}",
                                json={"body": body})
        raise_for_status(resp)

    def list_open_prs(self, repo) -> list[PR]:
        rows = self._get(f"/projects/{self._enc(repo)}/merge_requests?state=opened")
        return [PR(platform=Platform.gitlab, repo=repo, number=r["iid"],
                   head_sha=r.get("sha", "")) for r in rows]

    def add_labels(self, repo, pr_number, labels) -> None:
        resp = self._client.put(self._mr(repo, pr_number),
                                json={"add_labels": ",".join(labels)})
        raise_for_status(resp)

    def assign_reviewers(self, repo, pr_number, reviewers) -> None:
        body = "Suggested reviewers: " + " ".join(f"@{r}" for r in reviewers)
        self._post(self._mr(repo, pr_number) + "/notes", {"body": body})
