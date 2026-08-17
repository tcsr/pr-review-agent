from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.config import Settings, LLMConfig, StoreConfig
from app.main import build_app


def _settings():
    return Settings(llm=LLMConfig(provider="fake"),
                    store=StoreConfig(url="sqlite:///:memory:"),
                    defaults_tasks=["summarize"], repos=[])


def test_build_app_returns_app_and_queue():
    app, queue = build_app(_settings())
    assert isinstance(app, FastAPI)
    # queue is usable: enqueue then claim
    queue.enqueue("github", "o/r", 1, "s", "summarize")
    assert queue.claim() is not None


def test_built_app_health_ok():
    app, _ = build_app(_settings())
    assert TestClient(app).get("/health").json() == {"status": "ok"}
