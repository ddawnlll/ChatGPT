import pytest
from fastapi.testclient import TestClient

from proxy.app import router as router_module
from proxy.app.main import create_app
from proxy.app.state import conversation_store

PI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": f"Tool {name}",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }
    for name in ["read", "write", "edit", "bash", "grep", "find", "ls"]
]

TOOL_CASES = [
    ("read", "inspect server.py", {"path": "server.py"}),
    ("write", "create app/server.py", {"path": "app/server.py", "content": "print('ok')\n"}),
    ("edit", "patch app/server.py", {"path": "app/server.py"}),
    ("bash", "run tests", {"command": "pytest -q"}),
    ("grep", "search for TODO", {"pattern": "TODO", "path": "."}),
    ("find", "locate python files", {"path": ".", "pattern": "*.py"}),
    ("ls", "list directory", {"path": "."}),
]


def make_client() -> TestClient:
    conversation_store.clear()
    return TestClient(create_app())


@pytest.mark.parametrize(("tool_name", "user_prompt", "arguments"), TOOL_CASES)
def test_pi_tool_request_returns_openai_tool_call(monkeypatch, tool_name, user_prompt, arguments):
    def fake_complete_chat_turn(**kwargs):
        import json
        return (
            f'<tool_call>{{"name":"{tool_name}","arguments":{json.dumps(arguments, separators=(",", ":"))}}}</tool_call>',
            "conv-test",
        )

    monkeypatch.setattr(router_module, "complete_chat_turn", fake_complete_chat_turn)

    client = make_client()
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "messages": [{"role": "user", "content": user_prompt}],
            "tools": PI_TOOLS,
        },
    )

    assert response.status_code == 200
    choice = response.json()["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    tool_call = choice["message"]["tool_calls"][0]
    assert tool_call["type"] == "function"
    assert tool_call["function"]["name"] == tool_name


def test_pi_tool_follow_up_tool_result_returns_final_response(monkeypatch):
    def fake_complete_chat_turn(**kwargs):
        messages = kwargs["messages"]
        if any(message.get("role") == "tool" for message in messages):
            return ("<final_response>Done.</final_response>", "conv-test")
        return ('<tool_call>{"name":"read","arguments":{"path":"server.py"}}</tool_call>', "conv-test")

    monkeypatch.setattr(router_module, "complete_chat_turn", fake_complete_chat_turn)

    client = make_client()

    first = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "messages": [{"role": "user", "content": "read server.py"}],
            "tools": PI_TOOLS,
        },
    )
    assert first.status_code == 200
    first_choice = first.json()["choices"][0]
    assert first_choice["finish_reason"] == "tool_calls"

    second = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "messages": [
                {"role": "user", "content": "read server.py"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": first_choice["message"]["tool_calls"],
                },
                {"role": "tool", "tool_call_id": first_choice["message"]["tool_calls"][0]["id"], "content": "file contents"},
            ],
            "tools": PI_TOOLS,
        },
    )

    assert second.status_code == 200
    second_choice = second.json()["choices"][0]
    assert second_choice["finish_reason"] == "stop"
    assert second_choice["message"]["content"] == "Done."
