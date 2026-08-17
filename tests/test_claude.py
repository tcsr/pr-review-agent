import httpx
from app.llm.claude import ClaudeAdapter
from app.llm.base import Message


def test_complete_maps_messages_and_response():
    seen = {}
    def handler(request):
        import json
        assert request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == "sk"
        assert request.headers["anthropic-version"] == "2023-06-01"
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={
            "content": [{"type": "text", "text": "Looks good."}],
            "usage": {"input_tokens": 10, "output_tokens": 3},
        })
    a = ClaudeAdapter("sk", "claude-sonnet-5", transport=httpx.MockTransport(handler))
    r = a.complete("be brief", [Message(role="user", content="review this")], max_tokens=100)
    assert r.text == "Looks good."
    assert r.usage_tokens == 13
    assert seen["system"] == "be brief"
    assert seen["messages"][0] == {"role": "user", "content": "review this"}
    assert seen["max_tokens"] == 100


def test_count_tokens():
    a = ClaudeAdapter("sk", "m", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    assert a.count_tokens("a b c") == 3
