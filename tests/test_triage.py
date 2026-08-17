from app.tasks.triage import TriageTask, _size_label, _type_label
from app.git.fake import FakeGitAdapter
from app.llm.fake import FakeLLMAdapter
from app.models import Diff, FileChange
from tests.fixtures import sample_meta


def _diff(lines):
    return Diff(files=[FileChange(path="a.py", patch="x", additions=lines, deletions=0,
                                 status="modified")])


def test_size_label_buckets():
    assert _size_label(5) == "size/XS"
    assert _size_label(30) == "size/S"
    assert _size_label(150) == "size/M"
    assert _size_label(400) == "size/L"
    assert _size_label(900) == "size/XL"


def test_type_label_from_title():
    assert _type_label("feat: add x") == "type/feature"
    assert _type_label("fix(core): y") == "type/fix"
    assert _type_label("docs: z") == "type/docs"
    assert _type_label("random title") is None


def test_triage_adds_size_and_type_labels():
    git = FakeGitAdapter(seed={("o/r", 1): (sample_meta(title="feat: add x"), _diff(5))})
    llm = FakeLLMAdapter(responses=[""])
    res = TriageTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1),
                           git.get_diff("o/r", 1))
    assert res.posted == 1
    assert "size/XS" in git.labels
    assert "type/feature" in git.labels


def test_triage_no_type_still_adds_size():
    git = FakeGitAdapter(seed={("o/r", 1): (sample_meta(title="random"), _diff(5))})
    llm = FakeLLMAdapter(responses=[""])
    TriageTask().run(git, llm, "o/r", 1, git.get_pr_meta("o/r", 1), git.get_diff("o/r", 1))
    assert git.labels == ["size/XS"]
