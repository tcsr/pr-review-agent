from __future__ import annotations

from app.models import Event, Platform

_ACCEPTED = {"opened", "synchronize", "reopened"}
_GL_ACCEPTED = {"open", "reopen", "update"}


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
            comment_author=comment.get("user", {}).get("login"),
        )
    return None


def parse_gitlab_event(payload: dict, event_type: str | None) -> Event | None:
    if event_type == "Merge Request Hook":
        attrs = payload.get("object_attributes", {})
        if attrs.get("action") not in _GL_ACCEPTED:
            return None
        return Event(
            platform=Platform.gitlab,
            repo=payload["project"]["path_with_namespace"],
            pr_number=attrs["iid"],
            head_sha=attrs["last_commit"]["id"],
            action=attrs["action"],
        )
    if event_type == "Note Hook":
        mr = payload.get("merge_request")
        if not mr:
            return None
        attrs = payload["object_attributes"]
        return Event(
            platform=Platform.gitlab,
            repo=payload["project"]["path_with_namespace"],
            pr_number=mr["iid"],
            head_sha=f"comment-{attrs['id']}",
            action="comment",
            comment_body=attrs.get("note", ""),
            comment_author=payload.get("user", {}).get("username"),
        )
    return None
