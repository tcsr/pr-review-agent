from __future__ import annotations

from app.http import build_client
from app.llm.base import LLMAdapter, Message, LLMResponse
from app.llm.http_llm import post_json


class OpenAIAdapter(LLMAdapter):
    def __init__(self, api_key: str, model: str,
                 base_url: str = "https://api.openai.com/v1", transport=None):
        self.model = model
        # Normalize base_url to end with trailing slash to preserve path when using relative paths
        normalized_base_url = base_url.rstrip("/") + "/"
        self._client = build_client(
            normalized_base_url,
            {"Authorization": f"Bearer {api_key}",
             "content-type": "application/json"},
            transport=transport,
        )

    def complete(self, system, messages, max_tokens) -> LLMResponse:
        payload_messages = [{"role": "system", "content": system}]
        payload_messages += [{"role": m.role, "content": m.content} for m in messages]
        data = post_json(self._client, "chat/completions", {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": payload_messages,
        })
        text = data["choices"][0]["message"]["content"]
        tokens = data.get("usage", {}).get("total_tokens", 0)
        return LLMResponse(text=text, usage_tokens=tokens)

    def count_tokens(self, text: str) -> int:
        return len(text.split())
