import pytest
from app.config import RepoConfig
from app.git.factory import build_git_adapter
from app.git.github import GitHubAdapter
from app.models import Platform


def test_builds_github_adapter():
    rc = RepoConfig(platform=Platform.github, full_name="o/r", token="t")
    a = build_git_adapter(rc)
    assert isinstance(a, GitHubAdapter)
    assert a.repo == "o/r"


def test_bitbucket_not_implemented():
    rc = RepoConfig(platform=Platform.bitbucket, full_name="o/r", token="t")
    with pytest.raises(NotImplementedError):
        build_git_adapter(rc)


def test_builds_gitlab_adapter():
    from app.git.gitlab import GitLabAdapter
    rc = RepoConfig(platform=Platform.gitlab, full_name="grp/proj", token="t")
    a = build_git_adapter(rc)
    assert isinstance(a, GitLabAdapter)
    assert a.repo == "grp/proj"


def test_gitlab_self_hosted_base_url():
    from app.git.gitlab import GitLabAdapter
    rc = RepoConfig(platform=Platform.gitlab, full_name="grp/proj", token="t",
                    base_url="https://gitlab.example.com/api/v4")
    a = build_git_adapter(rc)
    assert isinstance(a, GitLabAdapter)
