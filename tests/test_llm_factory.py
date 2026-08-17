import pytest
from app.config import LLMConfig
from app.llm.factory import build_llm_adapter
from app.llm.claude import ClaudeAdapter
from app.llm.openai import OpenAIAdapter
from app.llm.local import LocalAdapter
from app.llm.fake import FakeLLMAdapter


def test_fake():
    assert isinstance(build_llm_adapter(LLMConfig(provider="fake")), FakeLLMAdapter)


def test_claude():
    a = build_llm_adapter(LLMConfig(provider="claude", model="m", api_key="k"))
    assert isinstance(a, ClaudeAdapter)


def test_openai():
    a = build_llm_adapter(LLMConfig(provider="openai", model="m", api_key="k"))
    assert isinstance(a, OpenAIAdapter) and not isinstance(a, LocalAdapter)


def test_local():
    a = build_llm_adapter(LLMConfig(provider="local", model="m",
                                    base_url="http://localhost:11434/v1"))
    assert isinstance(a, LocalAdapter)


def test_unknown_raises():
    with pytest.raises(ValueError):
        build_llm_adapter(LLMConfig(provider="mystery"))
