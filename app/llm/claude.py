from __future__ import annotations

from app.http import build_client
from app.llm.base import LLMAdapter, Message, LLMResponse
from app.llm.http_llm import post_json


class ClaudeAdapter(LLMAdapter):
    def __init__(self, api_key: str, model: str, transport=None,
                 api_base: str = "https://api.anthropic.com"):
        self.model = model
        self._client = build_client(
            api_base,
            {"x-api-key": api_key, "anthropic-version": "2023-06-01",
             "content-type": "application/json"},
            transport=transport,
        )

    def complete(self, system, messages, max_tokens) -> LLMResponse:
        data = post_json(self._client, "/v1/messages", {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        })
        text = "".join(b.get("text", "") for b in data.get("content", [])
                       if b.get("type") == "text")
        usage = data.get("usage", {})
        tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        return LLMResponse(text=text, usage_tokens=tokens)

    def count_tokens(self, text: str) -> int:
        return len(text.split())
