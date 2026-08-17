from __future__ import annotations

from app.config import LLMConfig
from app.llm.base import LLMAdapter
from app.llm.fake import FakeLLMAdapter
from app.llm.claude import ClaudeAdapter
from app.llm.openai import OpenAIAdapter
from app.llm.local import LocalAdapter


def build_llm_adapter(cfg: LLMConfig, transport=None) -> LLMAdapter:
    p = cfg.provider
    if p == "fake":
        return FakeLLMAdapter(responses=[""])
    if p == "claude":
        return ClaudeAdapter(cfg.api_key, cfg.model, transport=transport)
    if p == "openai":
        return OpenAIAdapter(cfg.api_key, cfg.model,
                             base_url=cfg.base_url or "https://api.openai.com/v1",
                             transport=transport)
    if p == "local":
        return LocalAdapter(cfg.model, cfg.base_url or "http://localhost:11434/v1",
                            api_key=cfg.api_key, transport=transport)
    raise ValueError(f"Unknown LLM provider: {p}")
