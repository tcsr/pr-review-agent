from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Message:
    role: str
    content: str


@dataclass
class LLMResponse:
    text: str
    usage_tokens: int = 0


class LLMAdapter(ABC):
    @abstractmethod
    def complete(self, system: str, messages: list[Message], max_tokens: int) -> LLMResponse: ...

    @abstractmethod
    def count_tokens(self, text: str) -> int: ...
