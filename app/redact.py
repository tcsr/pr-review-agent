from __future__ import annotations

import re

from app.models import Diff, FileChange

_REDACTED = "***REDACTED***"

_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
]
_ASSIGN = re.compile(
    r"(?i)(api[_-]?key|secret|token|password)(\s*[:=]\s*)['\"]?[A-Za-z0-9._\-]{8,}['\"]?"
)


def redact_text(text: str) -> str:
    for pat in _PATTERNS:
        text = pat.sub(_REDACTED, text)
    text = _ASSIGN.sub(lambda m: f"{m.group(1)}{m.group(2)}{_REDACTED}", text)
    return text


def redact_diff(diff: Diff) -> Diff:
    return Diff(files=[
        FileChange(path=f.path, patch=redact_text(f.patch), additions=f.additions,
                   deletions=f.deletions, status=f.status)
        for f in diff.files
    ])
