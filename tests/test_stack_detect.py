from app.stack.detect import detect_stacks
from app.models import Diff, FileChange


def _diff(paths):
    return Diff(files=[FileChange(path=p, patch="", additions=1, deletions=0,
                                  status="modified") for p in paths])


def test_extensions():
    assert detect_stacks(_diff(["a.py"])) == {"python"}
    assert detect_stacks(_diff(["Main.java"])) == {"java"}
    assert detect_stacks(_diff(["a.tsx"])) == {"react"}
    assert "css" in detect_stacks(_diff(["style.scss"]))


def test_filename_signals():
    assert "angular" in detect_stacks(_diff(["angular.json"]))
    assert "nestjs" in detect_stacks(_diff(["nest-cli.json"]))
    assert "nextjs" in detect_stacks(_diff(["next.config.js"]))
    assert "node" in detect_stacks(_diff(["package.json"]))


def test_multi_stack():
    got = detect_stacks(_diff(["src/api/main.ts", "nest-cli.json", "ui/app.tsx"]))
    assert "nestjs" in got and "react" in got


def test_empty():
    assert detect_stacks(_diff([])) == set()
