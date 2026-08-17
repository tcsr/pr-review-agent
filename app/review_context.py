from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReviewContext:
    review_criteria: list[str] = field(default_factory=list)
    gates: dict = field(default_factory=dict)
    stacks: set[str] = field(default_factory=set)
    bot_handle: str = ""
