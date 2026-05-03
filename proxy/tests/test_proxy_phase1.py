from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient

from proxy.app import client as proxy_client
from proxy.app.config import settings
from proxy.app.main import create_app
from proxy.app.state import conversation_store
from proxy.app.streaming import chat_completions_stream
from proxy.app.tools_shim import parse_assistant_action


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
        self.data: dict[str, str] = {}

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


def test_history_based_conversation_reuse_supports_pi_style_full_history(monkeypatch):
    stub = BuildTransportStub()
    monkeypatch.setattr(proxy_client, "build_transport", stub)
    client = make_client()

    first = client.post("/v1/chat/completions", json={"model": "chatgpt-playwright", "messages": [{"role": "user", "content": "first"}]})
    assert first.status_code == 200
    assistant_reply = first.json()["choices"][0]["message"]["content"]

    second = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "messages": [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": assistant_reply},
                {"role": "user", "content": "second"},
            ],
        },
    )
    assert second.status_code == 200
    assert len(stub.transports) == 1
    assert stub.transports[0].calls == [("first", True), ("second", False)]


def test_persisted_history_alias_rehydrates_transport(monkeypatch):
    stub = BuildTransportStub()
    monkeypatch.setattr(proxy_client, "build_transport", stub)
    client = make_client()

    first = client.post("/v1/chat/completions", json={"model": "chatgpt-playwright", "messages": [{"role": "user", "content": "first"}]})
    assert first.status_code == 200
    assistant_reply = first.json()["choices"][0]["message"]["content"]

    # Simulate process-local transport loss but persistent proxy memory retained.
    state = conversation_store.count()
    assert state == 1
    only_state = next(iter(conversation_store._items.values()))
    only_state.transport = None

    second = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "messages": [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": assistant_reply},
                {"role": "user", "content": "second"},
            ],
        },
    )
    assert second.status_code == 200
    assert len(stub.transports) == 2
    # New transport should still continue existing remote conversation, not start new one.
    assert stub.transports[1].calls == [("second", False)]
    assert stub.transports[1].data.get("conversation_id") == "remote-conv"


def test_pi_tool_request_returns_tool_call_response(monkeypatch):
    stub = BuildTransportStub()
    monkeypatch.setattr(proxy_client, "build_transport", stub)
    stub_transport = FakeTransport()
    stub_transport.send_message = lambda message, image=None, new_conversation=True: FakeResult('<tool_call>{"name":"write","arguments":{"filename":"server.py","content":"print(1)"}}</tool_call>')
    stub.transports = [stub_transport]
    monkeypatch.setattr(proxy_client, "build_transport", lambda session_material: stub_transport)
    client = make_client()

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "messages": [{"role": "user", "content": "write a python web server"}],
            "tools": [{"type": "function", "function": {"name": "write", "description": "Write a file", "parameters": {"type": "object"}}}],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    choice = payload["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"][0]["function"]["name"] == "write"


def test_pi_tool_request_stream_returns_tool_call_chunk(monkeypatch):
    stub_transport = FakeTransport()
    stub_transport.send_message = lambda message, image=None, new_conversation=True: FakeResult('<tool_call>{"name":"bash","arguments":{"command":"python server.py"}}</tool_call>')
    monkeypatch.setattr(proxy_client, "build_transport", lambda session_material: stub_transport)
    client = make_client()

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "stream": True,
            "messages": [{"role": "user", "content": "run the server"}],
            "tools": [{"type": "function", "function": {"name": "bash", "description": "Run shell command", "parameters": {"type": "object"}}}],
        },
    )
    assert response.status_code == 200
    assert 'tool_calls' in response.text
    assert 'python server.py' in response.text
    assert '[DONE]' in response.text


def test_parse_assistant_action_recovers_malformed_write_with_triple_quotes():
    raw = (
        '<tool_call>{"name":"write","arguments":{"path":"app/server.py","content":"#!/usr/bin/env python3\\n"""A small Python web server using only the standard library."""\\n\\nprint(\"ok\")\\n"}}</tool_call>'
    )
    action = parse_assistant_action(raw)
    assert action.kind == "tool"
    assert action.tool_name == "write"
    assert action.tool_arguments == {
        "path": "app/server.py",
        "content": '#!/usr/bin/env python3\n"""A small Python web server using only the standard library."""\n\nprint("ok")\n',
    }


def test_parse_assistant_action_supports_safe_write_content_block():
    raw = (
        '<tool_call>{"name":"write","arguments":{"path":"app/server.py"}}</tool_call>\n'
        '<write_content>\n#!/usr/bin/env python3\n"""doc"""\nprint("ok")\n</write_content>'
    )
    action = parse_assistant_action(raw)
    assert action.kind == "tool"
    assert action.tool_arguments == {
        "path": "app/server.py",
        "content": '#!/usr/bin/env python3\n"""doc"""\nprint("ok")\n',
    }


def test_pi_tool_request_recovers_malformed_write_and_returns_tool_call(monkeypatch):
    malformed = (
        '<tool_call>{"name":"write","arguments":{"path":"app/server.py","content":"#!/usr/bin/env python3\\n"""A small Python web server using only the standard library."""\\n\\nprint(\"ok\")\\n"}}</tool_call>'
    )
    stub_transport = FakeTransport()
    stub_transport.send_message = lambda message, image=None, new_conversation=True: FakeResult(malformed)
    monkeypatch.setattr(proxy_client, "build_transport", lambda session_material: stub_transport)
    client = make_client()

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "messages": [{"role": "user", "content": "write app/server.py"}],
            "tools": [{"type": "function", "function": {"name": "write", "description": "Write a file", "parameters": {"type": "object"}}}],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    call = payload["choices"][0]["message"]["tool_calls"][0]
    assert call["function"]["name"] == "write"
    arguments = json.loads(call["function"]["arguments"])
    assert arguments["path"] == "app/server.py"
    assert '"""A small Python web server using only the standard library."""' in arguments["content"]


def test_pi_tool_request_invalid_tool_call_returns_error_instead_of_raw_text(monkeypatch):
    stub_transport = FakeTransport()
    stub_transport.send_message = lambda message, image=None, new_conversation=True: FakeResult('<tool_call>{"name":"write","arguments":{"path":"app/server.py"}}</tool_call>')
    monkeypatch.setattr(proxy_client, "build_transport", lambda session_material: stub_transport)
    client = make_client()

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "messages": [{"role": "user", "content": "write app/server.py"}],
            "tools": [{"type": "function", "function": {"name": "write", "description": "Write a file", "parameters": {"type": "object"}}}],
        },
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "malformed_tool_call"


def test_parse_assistant_action_rejects_invalid_python_write_content():
    raw = (
        '<tool_call>{"name":"write","arguments":{"path":"app/server.py"}}</tool_call>\n'
        '<write_content>\n#!/usr/bin/env python3\nclass RequestHandler:\ndef broken(self):\nprint("oops")\n</write_content>'
    )
    action = parse_assistant_action(raw)
    assert action.kind == "invalid_tool"
    assert "syntax validation" in (action.parse_error or "")


def test_pi_tool_request_retries_malformed_python_write_once(monkeypatch):
    bad = '<tool_call>{"name":"write","arguments":{"path":"app/server.py"}}</tool_call>\n<write_content>\nclass Broken:\ndef x(self):\nprint("oops")\n</write_content>'
    fixed = '<tool_call>{"name":"write","arguments":{"path":"app/server.py"}}</tool_call>\n<write_content>\nclass Broken:\n    def x(self):\n        print("oops")\n</write_content>'
    stub_transport = FakeTransport()

    def send_message(message, image=None, new_conversation=True):
        stub_transport.calls.append((message, new_conversation, message))
        if len(stub_transport.calls) == 1:
            stub_transport.last_result = FakeResult(bad)
        else:
            stub_transport.last_result = FakeResult(fixed)
        return stub_transport.last_result

    stub_transport.send_message = send_message
    monkeypatch.setattr(proxy_client, "build_transport", lambda session_material: stub_transport)
    client = make_client()

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "messages": [{"role": "user", "content": "write app/server.py"}],
            "tools": [{"type": "function", "function": {"name": "write", "description": "Write a file", "parameters": {"type": "object"}}}],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    call = payload["choices"][0]["message"]["tool_calls"][0]
    arguments = json.loads(call["function"]["arguments"])
    assert arguments["content"] == 'class Broken:\n    def x(self):\n        print("oops")\n'
    assert len(stub_transport.calls) == 2
    assert stub_transport.calls[0][1] is True
    assert stub_transport.calls[1][1] is False
    assert "Validation error:" in stub_transport.calls[1][2]


def test_tool_call_follow_up_reuses_same_transport(monkeypatch):
    tool_call_response = '<tool_call>{"name":"write","arguments":{"path":"app/server.py"}}</tool_call>\n<write_content>print("ok")\n</write_content>'
    final_response = '<final_response>Created `app/server.py`.</final_response>'
    stub_transport = FakeTransport()

    def send_message(message, image=None, new_conversation=True):
        stub_transport.calls.append((message, new_conversation))
        if len(stub_transport.calls) == 1:
            stub_transport.last_result = FakeResult(tool_call_response)
        else:
            stub_transport.last_result = FakeResult(final_response)
        return stub_transport.last_result

    stub_transport.send_message = send_message
    monkeypatch.setattr(proxy_client, "build_transport", lambda session_material: stub_transport)
    client = make_client()

    first = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "messages": [{"role": "user", "content": "write app/server.py"}],
            "tools": [{"type": "function", "function": {"name": "write", "description": "Write a file", "parameters": {"type": "object"}}}],
        },
    )
    assert first.status_code == 200
    tool_call = first.json()["choices"][0]["message"]["tool_calls"][0]

    second = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "messages": [
                {"role": "user", "content": "write app/server.py"},
                {"role": "assistant", "content": None, "tool_calls": [tool_call]},
                {"role": "tool", "tool_call_id": tool_call["id"], "content": "Successfully wrote file"},
            ],
            "tools": [{"type": "function", "function": {"name": "write", "description": "Write a file", "parameters": {"type": "object"}}}],
        },
    )
    assert second.status_code == 200
    assert stub_transport.calls[0][1] is True
    assert stub_transport.calls[1][1] is False


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
