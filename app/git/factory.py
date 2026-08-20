from __future__ import annotations

from app.config import RepoConfig
from app.git.base import GitPlatformAdapter
from app.git.github import GitHubAdapter
from app.git.gitlab import GitLabAdapter
from app.models import Platform


def build_git_adapter(repo_config: RepoConfig, transport=None) -> GitPlatformAdapter:
    if repo_config.platform == Platform.github:
        return GitHubAdapter(repo_config.full_name, repo_config.token,
                             transport=transport)
    if repo_config.platform == Platform.gitlab:
        return GitLabAdapter(repo_config.full_name, repo_config.token,
                             transport=transport,
                             api_base=repo_config.base_url or "https://gitlab.com/api/v4")
    if repo_config.platform == Platform.bitbucket:
        raise NotImplementedError("bitbucket adapter not yet implemented")
    raise ValueError(f"Unknown platform: {repo_config.platform}")
