from __future__ import annotations

from typing import Callable

from app.llm.base import LLMAdapter, Message, LLMResponse


class FakeLLMAdapter(LLMAdapter):
    def __init__(self, responses: list[str] | None = None,
                 responder: Callable[[str, list[Message]], str] | None = None):
        self._responses = responses or []
        self._responder = responder
        self._i = 0
        self.calls: list[tuple[str, list[Message]]] = []

    def complete(self, system, messages, max_tokens) -> LLMResponse:
        self.calls.append((system, messages))
        if self._responder is not None:
            text = self._responder(system, messages)
        elif self._responses:
            text = self._responses[min(self._i, len(self._responses) - 1)]
            self._i += 1
        else:
            text = ""
        return LLMResponse(text=text, usage_tokens=self.count_tokens(text))

    def count_tokens(self, text: str) -> int:
        return len(text.split())
