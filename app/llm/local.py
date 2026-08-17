from __future__ import annotations

from app.llm.openai import OpenAIAdapter


class LocalAdapter(OpenAIAdapter):
    def __init__(self, model: str, base_url: str, api_key: str = "", transport=None):
        super().__init__(api_key=api_key, model=model, base_url=base_url,
                         transport=transport)
