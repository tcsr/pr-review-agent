from __future__ import annotations

import os

_EXT = {
    ".py": "python", ".java": "java", ".css": "css", ".scss": "css",
    ".tsx": "react", ".jsx": "react", ".ts": "typescript", ".js": "javascript",
}
_FILENAME = {
    "angular.json": "angular", "nest-cli.json": "nestjs",
    "next.config.js": "nextjs", "next.config.ts": "nextjs",
    "package.json": "node",
}


def detect_stacks(diff) -> set[str]:
    stacks: set[str] = set()
    for f in diff.files:
        base = os.path.basename(f.path)
        if base in _FILENAME:
            stacks.add(_FILENAME[base])
        ext = os.path.splitext(f.path)[1].lower()
        if ext in _EXT:
            stacks.add(_EXT[ext])
    return stacks
