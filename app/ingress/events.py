from __future__ import annotations

from app.models import Event, Platform

_ACCEPTED = {"opened", "synchronize", "reopened"}


def parse_github_event(payload: dict, event_type: str | None) -> Event | None:
    if event_type != "pull_request":
        return None
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
