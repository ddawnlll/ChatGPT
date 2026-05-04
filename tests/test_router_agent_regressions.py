from fastapi.testclient import TestClient

from proxy.app.main import create_app
from proxy.app.state import conversation_store

PI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": "Read file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
            },
        },
    }
]


def make_client() -> TestClient:
    conversation_store.clear()
    return TestClient(create_app())


def test_agent_final_response_does_not_leak_prompt_placeholder(monkeypatch):
    def fake_complete_chat_turn(**kwargs):
        return (
            """
<final_response>your final answer here</final_response>
<final_response>Ready.</final_response>
""",
            "conv-test",
        )

    monkeypatch.setattr("proxy.app.router.complete_chat_turn", fake_complete_chat_turn)

    client = make_client()
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "stream": False,
            "messages": [{"role": "user", "content": "hi"}],
            "tools": PI_TOOLS,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["choices"][0]["message"]["content"] == "Ready."
    assert "your final answer here" not in payload["choices"][0]["message"]["content"]


def test_agent_tool_call_response_shape(monkeypatch):
    def fake_complete_chat_turn(**kwargs):
        return (
            '<tool_call>{"name":"read","arguments":{"path":"server.py"}}</tool_call>',
            "conv-test",
        )

    monkeypatch.setattr("proxy.app.router.complete_chat_turn", fake_complete_chat_turn)

    client = make_client()
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "stream": False,
            "messages": [{"role": "user", "content": "read server.py"}],
            "tools": PI_TOOLS,
        },
    )

    assert response.status_code == 200
    choice = response.json()["choices"][0]

    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"][0]["type"] == "function"
    assert choice["message"]["tool_calls"][0]["function"]["name"] == "read"


def test_agent_streaming_transport_exception_returns_structured_sse_error(monkeypatch):
    def fake_complete_chat_turn(**kwargs):
        raise RuntimeError("Playwright transport failed: boom")

    monkeypatch.setattr("proxy.app.router.complete_chat_turn", fake_complete_chat_turn)

    client = make_client()
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
            "tools": PI_TOOLS,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert '"code":"transport_error"' in response.text
    assert "Playwright transport failed: boom" in response.text
    assert response.text.rstrip().endswith("data: [DONE]")
