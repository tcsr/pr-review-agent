from __future__ import annotations

from app.config import RepoConfig
from app.git.base import GitPlatformAdapter
from app.git.github import GitHubAdapter
from app.models import Platform


def build_git_adapter(repo_config: RepoConfig, transport=None) -> GitPlatformAdapter:
    if repo_config.platform == Platform.github:
        return GitHubAdapter(repo_config.full_name, repo_config.token,
                             transport=transport)
    if repo_config.platform in (Platform.bitbucket, Platform.gitlab):
        raise NotImplementedError(
            f"{repo_config.platform.value} adapter not yet implemented")
    raise ValueError(f"Unknown platform: {repo_config.platform}")
