from __future__ import annotations

from app.config import find_repo, resolve_rules, resolve_stacks
from app.git.factory import build_git_adapter
from app.llm.factory import build_llm_adapter
from app.reviewer import Reviewer


def process_one(queue, settings, transport_git=None, transport_llm=None) -> bool:
    job = queue.claim()
    if job is None:
        return False
    try:
        repo_cfg = find_repo(settings, job.platform, job.repo)
        if repo_cfg is None:
            raise ValueError(f"No repo config for {job.platform}:{job.repo}")
        git = build_git_adapter(repo_cfg, transport=transport_git)
        llm = build_llm_adapter(settings.llm, transport=transport_llm)
        rules = resolve_rules(settings, repo_cfg)
        stacks_cfg = resolve_stacks(settings, repo_cfg)
        Reviewer(git, llm).review(job.repo, job.pr_number, [job.task],
                                  rules=rules, stacks_cfg=stacks_cfg)
        queue.complete(job.id)
    except Exception as e:  # worker never crashes the loop
        queue.fail(job.id, str(e))
    return True
