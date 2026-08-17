import httpx
from app.llm.openai import OpenAIAdapter
from app.llm.local import LocalAdapter
from app.llm.base import Message


def _resp():
    return {"choices": [{"message": {"content": "ok"}}],
            "usage": {"total_tokens": 42}}


def test_openai_complete_maps():
    seen = {}
    def handler(request):
        import json
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer sk"
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=_resp())
    a = OpenAIAdapter("sk", "gpt-x", transport=httpx.MockTransport(handler))
    r = a.complete("sys", [Message(role="user", content="hi")], max_tokens=50)
    assert r.text == "ok"
    assert r.usage_tokens == 42
    assert seen["messages"][0] == {"role": "system", "content": "sys"}
    assert seen["messages"][1] == {"role": "user", "content": "hi"}


def test_local_uses_given_base_url():
    hit = {}
    def handler(request):
        hit["host"] = request.url.host
        hit["path"] = request.url.path
        return httpx.Response(200, json=_resp())
    a = LocalAdapter("llama", "http://localhost:11434/v1",
                     transport=httpx.MockTransport(handler))
    r = a.complete("s", [Message(role="user", content="x")], max_tokens=10)
    assert r.text == "ok"
    assert hit["host"] == "localhost"
    assert hit["path"] == "/v1/chat/completions"
