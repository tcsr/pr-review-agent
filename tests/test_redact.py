from app.redact import redact_text, redact_diff
from app.models import Diff, FileChange


def test_redacts_openai_key():
    out = redact_text("token = sk-abcdefghijklmnopqrstuvwxyz012345")
    assert "sk-abcdefghijk" not in out
    assert "REDACTED" in out


def test_redacts_github_and_aws():
    assert "REDACTED" in redact_text("ghp_" + "a" * 36)
    assert "REDACTED" in redact_text("AKIA" + "ABCDEFGHIJKLMNOP")


def test_redacts_generic_assignment():
    out = redact_text('API_KEY = "hunter2secretvalue"')
    assert "hunter2secretvalue" not in out
    assert "REDACTED" in out


def test_leaves_ordinary_code_untouched():
    code = "def add(a, b):\n    return a + b"
    assert redact_text(code) == code


def test_redact_diff_preserves_metadata_and_scrubs_patch():
    d = Diff(files=[FileChange(path="a.py", patch="key = sk-abcdefghijklmnopqrstuvwxyz012345",
                              additions=1, deletions=0, status="modified")])
    out = redact_diff(d)
    assert out.files[0].path == "a.py"
    assert out.files[0].additions == 1
    assert "REDACTED" in out.files[0].patch
    # original untouched
    assert "sk-abcdefghijk" in d.files[0].patch
