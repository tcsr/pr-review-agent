from __future__ import annotations

import fnmatch

from app.models import Diff


def apply_budget(diff, count_tokens, max_tokens: int, skip_globs: list[str]) -> tuple[Diff, bool]:
    candidates = [f for f in diff.files
                  if not any(fnmatch.fnmatch(f.path, g) for g in skip_globs)]
    ordered = sorted(candidates, key=lambda f: f.additions + f.deletions, reverse=True)
    kept, used = [], 0
    for f in ordered:
        cost = count_tokens(f.patch)
        if kept and used + cost > max_tokens:
            continue
        kept.append(f)
        used += cost
    truncated = len(kept) < len(candidates)
    return Diff(files=kept), truncated
