from app.models import PRMeta, Diff, FileChange


def sample_meta(**over) -> PRMeta:
    base = dict(title="Add feature", body="Does a thing", author="alice",
                base_sha="base1", head_sha="head1", labels=[], linked_issues=["#5"],
                ci_passed=True)
    base.update(over)
    return PRMeta(**base)


def sample_diff() -> Diff:
    return Diff(files=[
        FileChange(path="src/app.py", patch="@@ -1 +1 @@\n-old\n+new",
                   additions=1, deletions=1, status="modified"),
    ])
