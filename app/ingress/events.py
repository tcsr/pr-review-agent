from __future__ import annotations

from app.models import Event, Platform

_ACCEPTED = {"opened", "synchronize", "reopened"}


def parse_github_event(payload: dict, event_type: str | None) -> Event | None:
    if event_type == "pull_request":
        if payload.get("action") not in _ACCEPTED:
            return None
        pr = payload["pull_request"]
        return Event(
            platform=Platform.github,
            repo=payload["repository"]["full_name"],
            pr_number=pr["number"],
            head_sha=pr["head"]["sha"],
            action=payload["action"],
        )
    if event_type == "issue_comment":
        if payload.get("action") != "created":
            return None
        issue = payload.get("issue", {})
        if not issue.get("pull_request"):
            return None
        comment = payload["comment"]
        return Event(
            platform=Platform.github,
            repo=payload["repository"]["full_name"],
            pr_number=issue["number"],
            head_sha=f"comment-{comment['id']}",
            action="comment",
            comment_body=comment["body"],
        )
    return None
