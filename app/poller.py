from __future__ import annotations

from app.config import resolve_tasks
from app.git.factory import build_git_adapter
from app.models import Event


def poll_once(settings, queue, adapter_for=None) -> int:
    total = 0
    for repo_cfg in settings.repos:
        try:
            adapter = adapter_for(repo_cfg) if adapter_for else build_git_adapter(repo_cfg)
            prs = adapter.list_open_prs(repo_cfg.full_name)
            tasks = resolve_tasks(settings, repo_cfg)
            for pr in prs:
                event = Event(platform=repo_cfg.platform, repo=repo_cfg.full_name,
                              pr_number=pr.number, head_sha=pr.head_sha, action="poll")
                total += len(queue.enqueue_event(event, tasks))
        except Exception:
            continue  # one bad repo must not stop the sweep
    return total
