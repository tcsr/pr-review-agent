from __future__ import annotations


def post_or_update(git, repo, pr_number, marker: str, body: str) -> str:
    """
    Post or update a comment with an idempotency marker.

    Appends a hidden HTML comment marker to the body. If a comment with that marker
    already exists in the thread, update it instead of posting a new one.

    Args:
        git: GitPlatformAdapter instance
        repo: Repository identifier (e.g., "owner/repo")
        pr_number: Pull request number
        marker: Idempotency marker (e.g., "pr-agent:summarize")
        body: Comment body text

    Returns:
        Comment ID (either existing or newly posted)
    """
    tagged = f"{body}\n\n<!-- {marker} -->"
    for c in git.get_thread(repo, pr_number):
        if marker in (c.body or ""):
            git.update_comment(repo, pr_number, c.id, tagged)
            return c.id
    return git.post_comment(repo, pr_number, tagged)
