import httpx
import pytest
from app.errors import AdapterError
from app.http import build_client, raise_for_status


def test_adapter_error_message():
    e = AdapterError(404, "not found")
    assert e.status == 404
    assert "404" in str(e) and "not found" in str(e)


def test_raise_for_status_raises_on_4xx():
    resp = httpx.Response(403, text="forbidden")
    with pytest.raises(AdapterError) as ei:
        raise_for_status(resp)
    assert ei.value.status == 403


def test_raise_for_status_ok_on_200():
    raise_for_status(httpx.Response(200, text="ok"))  # no raise


def test_raise_for_status_raises_on_5xx():
    resp = httpx.Response(503, text="unavailable")
    with pytest.raises(AdapterError) as ei:
        raise_for_status(resp)
    assert ei.value.status == 503


def test_build_client_uses_transport():
    def handler(request):
        return httpx.Response(200, json={"seen": str(request.url)})
    client = build_client("https://api.example.com", {"X-Test": "1"},
                          transport=httpx.MockTransport(handler))
    r = client.get("/ping")
    assert r.status_code == 200
    assert "api.example.com/ping" in r.json()["seen"]
    assert client.headers["X-Test"] == "1"
