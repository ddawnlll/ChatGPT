from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient

from proxy.app import client as proxy_client
from proxy.app.config import settings
from proxy.app.main import create_app
from proxy.app.state import conversation_store
from proxy.app.streaming import chat_completions_stream


def make_client() -> TestClient:
    return TestClient(create_app())


class FakeResult:
    def __init__(self, text: str, remote_conversation_id: str = "remote-conv", remote_parent_message_id: str = "remote-parent"):
        self.text = text
        self.remote_conversation_id = remote_conversation_id
        self.remote_parent_message_id = remote_parent_message_id
        self.transport_details = {"transport_mode": "playwright"}
        self.verification_hints = {}


class FakeTransport:
    def __init__(self):
        self.calls: list[tuple[str, bool]] = []
        self.last_result = FakeResult("assistant reply")

    def send_message(self, message: str, image: str | None = None, *, new_conversation: bool = True):
        self.calls.append((message, new_conversation))
        self.last_result = FakeResult(f"reply:{message}")
        return self.last_result

    def stream_message(self, message: str, image: str | None = None, *, new_conversation: bool = True):
        self.calls.append((message, new_conversation))
        self.last_result = FakeResult(f"reply:{message}")
        for part in ["reply:", message]:
            yield part

    def get_last_result(self):
        return self.last_result


class BuildTransportStub:
    def __init__(self):
        self.calls = []
        self.transports: list[FakeTransport] = []

    def __call__(self, session_material):
        self.calls.append(dict(session_material))
        transport = FakeTransport()
        self.transports.append(transport)
        return transport


def setup_function():
    conversation_store.clear()


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


def test_chat_completions_non_streaming_executes_runtime(monkeypatch):
    stub = BuildTransportStub()
    monkeypatch.setattr(proxy_client, "build_transport", stub)
    client = make_client()

    response = client.post("/v1/chat/completions", json={"model": "chatgpt-playwright", "messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 200
    payload = response.json()
    assert payload["choices"][0]["message"]["content"] == "reply:hi"
    assert stub.calls[0]["transport_mode"] == "playwright"
    assert stub.calls[0]["thinking_mode"] == "extended"
    assert stub.transports[0].calls == [("hi", True)]


def test_chat_completions_streaming_returns_event_stream(monkeypatch):
    stub = BuildTransportStub()
    monkeypatch.setattr(proxy_client, "build_transport", stub)
    client = make_client()

    response = client.post("/v1/chat/completions", json={"model": "chatgpt-playwright", "stream": True, "messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "reply:" in response.text
    assert "[DONE]" in response.text
    assert stub.transports[0].calls == [("hi", True)]


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


def test_api_key_middleware_allows_valid_key(monkeypatch):
    stub = BuildTransportStub()
    monkeypatch.setattr(proxy_client, "build_transport", stub)
    original_key = settings.api_key
    settings.api_key = "secret-key"
    try:
        client = make_client()
        response = client.post("/v1/chat/completions", headers={"authorization": "Bearer secret-key"}, json={"model": "chatgpt-playwright", "messages": [{"role": "user", "content": "hi"}]})
        assert response.status_code == 200
        assert response.json()["choices"][0]["message"]["content"] == "reply:hi"
    finally:
        settings.api_key = original_key


def test_conversation_reuse_uses_existing_transport_and_marks_follow_up(monkeypatch):
    stub = BuildTransportStub()
    monkeypatch.setattr(proxy_client, "build_transport", stub)
    client = make_client()

    first = client.post("/v1/chat/completions", json={"model": "chatgpt-playwright", "user": "conv-1", "messages": [{"role": "user", "content": "first"}]})
    assert first.status_code == 200
    second = client.post("/v1/chat/completions", json={"model": "chatgpt-playwright", "user": "conv-1", "messages": [{"role": "user", "content": "second"}]})
    assert second.status_code == 200

    assert len(stub.transports) == 1
    assert stub.transports[0].calls == [("first", True), ("second", False)]


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
