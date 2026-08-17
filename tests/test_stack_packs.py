from app.stack.packs import BUILTIN_PACKS, pack_criteria
from app.config import StacksConfig


def test_builtin_packs_cover_expected_stacks():
    for s in ["angular", "react", "nextjs", "nestjs", "node", "java",
              "python", "javascript", "typescript", "css"]:
        assert s in BUILTIN_PACKS and BUILTIN_PACKS[s]


def test_pack_criteria_includes_detected():
    crit = pack_criteria({"python"}, StacksConfig())
    assert crit == BUILTIN_PACKS["python"]


def test_pack_criteria_disabled_pack_excluded():
    crit = pack_criteria({"react"}, StacksConfig(packs={"react": False}))
    assert crit == []


def test_pack_criteria_unknown_stack_ignored():
    assert pack_criteria({"cobol"}, StacksConfig()) == []


def test_pack_criteria_deterministic_order():
    a = pack_criteria({"python", "react"}, StacksConfig())
    b = pack_criteria({"react", "python"}, StacksConfig())
    assert a == b
