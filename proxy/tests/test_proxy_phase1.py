from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient

from proxy.app.config import settings
from proxy.app.main import create_app
from proxy.app.streaming import chat_completions_stream


def make_client() -> TestClient:
    return TestClient(create_app())


def test_health():
    client = make_client()
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["default_transport_mode"] == "playwright"
    assert payload["model_count"] >= 1


def test_models():
    client = make_client()
    response = client.get("/v1/models")
    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "list"
    ids = {item["id"] for item in payload["data"]}
    assert "chatgpt-playwright" in ids


def test_chat_completions_validation_requires_messages():
    client = make_client()
    response = client.post("/v1/chat/completions", json={"model": "chatgpt-playwright", "messages": []})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_messages"


def test_chat_completions_unknown_model_rejected():
    client = make_client()
    response = client.post("/v1/chat/completions", json={"model": "unknown", "messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "model_not_found"


def test_chat_completions_non_streaming_not_implemented_yet():
    client = make_client()
    response = client.post("/v1/chat/completions", json={"model": "chatgpt-playwright", "messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "not_implemented"


def test_chat_completions_streaming_returns_event_stream_even_before_runtime_wiring():
    client = make_client()
    response = client.post("/v1/chat/completions", json={"model": "chatgpt-playwright", "stream": True, "messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "not_implemented" in response.text
    assert "[DONE]" in response.text


def test_api_key_middleware_rejects_missing_or_invalid_key():
    original_key = settings.api_key
    settings.api_key = "secret-key"
    try:
        client = make_client()
        missing = client.post("/v1/chat/completions", json={"model": "chatgpt-playwright", "messages": [{"role": "user", "content": "hi"}]})
        assert missing.status_code == 401
        assert missing.json()["error"]["code"] == "invalid_api_key"

        invalid = client.post("/v1/chat/completions", headers={"authorization": "Bearer wrong"}, json={"model": "chatgpt-playwright", "messages": [{"role": "user", "content": "hi"}]})
        assert invalid.status_code == 401
        assert invalid.json()["error"]["code"] == "invalid_api_key"
    finally:
        settings.api_key = original_key


def test_api_key_middleware_allows_valid_key():
    original_key = settings.api_key
    settings.api_key = "secret-key"
    try:
        client = make_client()
        response = client.post("/v1/chat/completions", headers={"authorization": "Bearer secret-key"}, json={"model": "chatgpt-playwright", "messages": [{"role": "user", "content": "hi"}]})
        assert response.status_code == 501
        assert response.json()["error"]["code"] == "not_implemented"
    finally:
        settings.api_key = original_key


def test_streaming_formatter_emits_done():
    async def gen():
        yield "hello"
        yield " world"

    async def collect():
        return [item async for item in chat_completions_stream(gen(), "chatgpt-playwright", "chatcmpl-test")]

    events = asyncio.run(collect())
    assert events[-1] == "data: [DONE]\n\n"
    payloads = [json.loads(item.removeprefix("data: ").removesuffix("\n\n")) for item in events[:-1]]
    assert payloads[0]["choices"][0]["delta"]["role"] == "assistant"
    assert payloads[-1]["choices"][0]["finish_reason"] == "stop"
