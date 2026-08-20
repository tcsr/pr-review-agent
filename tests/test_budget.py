from app.budget import apply_budget
from app.models import Diff, FileChange


def _fc(path, patch, adds=1, dels=0):
    return FileChange(path=path, patch=patch, additions=adds, deletions=dels, status="modified")


def _count(text):
    return len(text.split())


def test_skip_globs_dropped_not_truncation():
    diff = Diff(files=[_fc("a.py", "x y"), _fc("pkg.lock", "a b c d")])
    out, truncated = apply_budget(diff, _count, 1000, ["*.lock"])
    assert [f.path for f in out.files] == ["a.py"]
    assert truncated is False   # skip is intentional, not truncation


def test_truncates_when_over_budget():
    diff = Diff(files=[_fc("big.py", "w " * 50, adds=50), _fc("small.py", "z", adds=1)])
    # budget fits only the bigger file (~50 tokens); small dropped
    out, truncated = apply_budget(diff, _count, 50, [])
    assert [f.path for f in out.files] == ["big.py"]
    assert truncated is True


def test_no_truncation_when_all_fit():
    diff = Diff(files=[_fc("a.py", "x"), _fc("b.py", "y")])
    out, truncated = apply_budget(diff, _count, 1000, [])
    assert len(out.files) == 2
    assert truncated is False


def test_keeps_at_least_one_when_first_exceeds():
    diff = Diff(files=[_fc("huge.py", "t " * 100, adds=100)])
    out, truncated = apply_budget(diff, _count, 10, [])
    assert len(out.files) == 1     # never drop everything
    assert truncated is False      # only one candidate, none dropped


def test_all_files_skipped_returns_empty_not_truncated():
    diff = Diff(files=[_fc("a.lock", "x"), _fc("b.lock", "y")])
    out, truncated = apply_budget(diff, _count, 1000, ["*.lock"])
    assert out.files == []
    assert truncated is False   # intentional skip, not truncation
