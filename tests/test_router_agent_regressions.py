import json

from fastapi.testclient import TestClient

from proxy.app import router as router_module
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

    monkeypatch.setattr(router_module, "complete_chat_turn", fake_complete_chat_turn)

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


def test_agent_final_response_wins_over_placeholder_tool_name(monkeypatch):
    def fake_complete_chat_turn(**kwargs):
        return (
            """
<tool_call>{"name":"tool_name","arguments":{}}</tool_call>
<final_response>Hello.</final_response>
""",
            "conv-test",
        )

    monkeypatch.setattr(router_module, "complete_chat_turn", fake_complete_chat_turn)

    client = make_client()
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "stream": False,
            "messages": [{"role": "user", "content": "say hello"}],
            "tools": PI_TOOLS,
        },
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "Hello."


def test_agent_tool_call_response_shape(monkeypatch):
    def fake_complete_chat_turn(**kwargs):
        return (
            '<tool_call>{"name":"read","arguments":{"path":"server.py"}}</tool_call>',
            "conv-test",
        )

    monkeypatch.setattr(router_module, "complete_chat_turn", fake_complete_chat_turn)

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


def test_agent_xml_bash_tool_call_response_shape(monkeypatch):
    def fake_complete_chat_turn(**kwargs):
        return (
            """
<tool_call>
<name>bash</name>
<arguments>
<timeout>10</timeout>
<command>
find app -print | sed 's|[^/]*/|  |g; s|  \\([^ ]\\)|├── \\1|'
</command>
</arguments>
</tool_call>
""",
            "conv-test",
        )

    monkeypatch.setattr(router_module, "complete_chat_turn", fake_complete_chat_turn)

    client = make_client()
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "stream": False,
            "messages": [{"role": "user", "content": "list files in app in tree"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "bash",
                        "description": "Run bash command",
                        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
                    },
                }
            ],
        },
    )

    assert response.status_code == 200
    choice = response.json()["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"][0]["function"]["name"] == "bash"
    assert "sed" in choice["message"]["tool_calls"][0]["function"]["arguments"]


def test_agent_multiple_tool_calls_response_shape(monkeypatch):
    def fake_complete_chat_turn(**kwargs):
        return (
            """
<tool_call><name>find</name><arguments><path>.</path><pattern>*.py</pattern></arguments></tool_call>
<tool_call><name>grep</name><arguments><path>.</path><pattern>TODO</pattern></arguments></tool_call>
""",
            "conv-test",
        )

    monkeypatch.setattr(router_module, "complete_chat_turn", fake_complete_chat_turn)
    client = make_client()
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "stream": False,
            "messages": [{"role": "user", "content": "find py files and search TODO"}],
            "tools": [
                {"type": "function", "function": {"name": "find", "description": "Find", "parameters": {"type": "object", "properties": {}}}},
                {"type": "function", "function": {"name": "grep", "description": "Grep", "parameters": {"type": "object", "properties": {}}}},
            ],
        },
    )

    assert response.status_code == 200
    tool_calls = response.json()["choices"][0]["message"]["tool_calls"]
    assert len(tool_calls) == 2
    assert [call["function"]["name"] for call in tool_calls] == ["find", "grep"]


def test_agent_streaming_transport_exception_returns_structured_sse_error(monkeypatch):
    def fake_complete_chat_turn(**kwargs):
        raise RuntimeError("Playwright transport failed: boom")

    monkeypatch.setattr(router_module, "complete_chat_turn", fake_complete_chat_turn)

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


def test_agent_incomplete_final_response_tag_returns_error(monkeypatch):
    def fake_complete_chat_turn(**kwargs):
        return ("<final", "conv-test")

    monkeypatch.setattr(router_module, "complete_chat_turn", fake_complete_chat_turn)

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

    assert response.status_code == 502
    payload = response.json()
    assert payload["error"]["code"] == "malformed_tool_call"
    assert "incomplete final_response tag" in payload["error"]["message"]


def test_agent_does_not_repair_placeholder_transport_artifact(monkeypatch):
    calls = []

    def fake_complete_chat_turn(**kwargs):
        calls.append(("turn", kwargs))
        return ("<tool_call>...</tool_call>", "conv-test")

    def fake_complete_chat(**kwargs):
        calls.append(("repair", kwargs))
        return "<final_response>should not happen</final_response>"

    monkeypatch.setattr(router_module, "complete_chat_turn", fake_complete_chat_turn)
    monkeypatch.setattr(router_module, "complete_chat", fake_complete_chat)

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

    assert response.status_code == 502
    assert not any(kind == "repair" for kind, _kwargs in calls)
    payload = response.json()
    assert payload["error"]["code"] == "malformed_tool_call"
    assert "placeholder transport artifact" in payload["error"]["message"]


def test_agent_does_not_repair_write_missing_content(monkeypatch):
    calls = []

    def fake_complete_chat_turn(**kwargs):
        calls.append(("turn", kwargs))
        return (
            """
<tool_call>
<name>write</name>
<arguments>
<path>server.py</path>
</arguments>
</tool_call>
""",
            "conv-test",
        )

    def fake_complete_chat(**kwargs):
        calls.append(("repair", kwargs))
        return "<final_response>should not happen</final_response>"

    monkeypatch.setattr(router_module, "complete_chat_turn", fake_complete_chat_turn)
    monkeypatch.setattr(router_module, "complete_chat", fake_complete_chat)

    client = make_client()
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "stream": False,
            "messages": [{"role": "user", "content": "write server.py"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "write",
                        "description": "Write file",
                        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
                    },
                }
            ],
        },
    )

    assert response.status_code == 502
    assert not any(kind == "repair" for kind, _kwargs in calls)
    payload = response.json()
    assert payload["error"]["code"] == "malformed_tool_call"
    assert "write tool call missing content" in payload["error"]["message"]


def test_agent_write_with_write_content_block_returns_content(monkeypatch):
    def fake_complete_chat_turn(**kwargs):
        return (
            """
<tool_call>
<name>write</name>
<arguments>
<path>server.py</path>
</arguments>
</tool_call>
<write_content>
```python
print(\"hello\")
```
</write_content>
""",
            "conv-test",
        )

    monkeypatch.setattr(router_module, "complete_chat_turn", fake_complete_chat_turn)

    client = make_client()
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "stream": False,
            "messages": [{"role": "user", "content": "write server.py"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "write",
                        "description": "Write file",
                        "parameters": {},
                    },
                }
            ],
        },
    )

    assert response.status_code == 200
    args = response.json()["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    parsed = json.loads(args)
    assert parsed["path"] == "server.py"
    assert parsed["content"] == 'print("hello")\n'



def test_agent_write_with_write_content_invalid_python_returns_syntax_error_without_repair(monkeypatch):
    calls = []

    def fake_complete_chat_turn(**kwargs):
        calls.append(("turn", kwargs))
        # This intentionally includes <write_content> with one fenced block
        # but invalid Python. The expected failure is syntax validation,
        # not missing content, and write failures must not trigger repair prompts.
        return (
            """
<tool_call>
<name>write</name>
<arguments>
<path>server.py</path>
</arguments>
</tool_call>
<write_content>
```python
class A:
def broken(self):
pass
```
</write_content>
""",
            "conv-test",
        )

    def fake_complete_chat(**kwargs):
        calls.append(("repair", kwargs))
        return "<final_response>should not happen</final_response>"

    monkeypatch.setattr(router_module, "complete_chat_turn", fake_complete_chat_turn)
    monkeypatch.setattr(router_module, "complete_chat", fake_complete_chat)

    client = make_client()
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "stream": False,
            "messages": [{"role": "user", "content": "write server.py"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "write",
                        "description": "Write file",
                        "parameters": {},
                    },
                }
            ],
        },
    )

    assert response.status_code == 502
    assert not any(kind == "repair" for kind, _kwargs in calls)
    payload = response.json()
    assert payload["error"]["code"] == "malformed_tool_call"
    assert "python write content failed syntax validation" in payload["error"]["message"]



def test_agent_retries_malformed_tool_call_and_returns_repaired_tool(monkeypatch):
    calls = []

    def fake_complete_chat_turn(**kwargs):
        calls.append(("turn", kwargs))
        return ('<tool_call>{"name":"edit","arguments":{"path":"app/test.py" "edits":[]}}</tool_call>', "conv-test")

    def fake_complete_chat(**kwargs):
        calls.append(("repair", kwargs))
        return '<tool_call>{"name":"edit","arguments":{"path":"app/test.py","edits":[{"oldText":"print(1)","newText":"print(2)"}]}}</tool_call>'

    monkeypatch.setattr(router_module, "complete_chat_turn", fake_complete_chat_turn)
    monkeypatch.setattr(router_module, "complete_chat", fake_complete_chat)

    client = make_client()
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "stream": False,
            "messages": [{"role": "user", "content": "add something more to file"}],
            "tools": [
                *PI_TOOLS,
                {
                    "type": "function",
                    "function": {
                        "name": "edit",
                        "description": "Edit file",
                        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
                    },
                },
            ],
        },
    )

    assert response.status_code == 200
    choice = response.json()["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"][0]["function"]["name"] == "edit"
    assert any(kind == "repair" for kind, _kwargs in calls)


def test_agent_prompt_includes_request_tool_hints(monkeypatch):
    captured = {}

    def fake_complete_chat_turn(**kwargs):
        captured["prompt_override"] = kwargs.get("prompt_override")
        return ('<tool_call>{"name":"read","arguments":{"path":"server.py"}}</tool_call>', "conv-test")

    monkeypatch.setattr(router_module, "complete_chat_turn", fake_complete_chat_turn)

    client = make_client()
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "stream": False,
            "messages": [{"role": "user", "content": "analyze the repo"}],
            "tools": PI_TOOLS,
            "parallel_tool_calls": True,
            "tool_choice": "required",
        },
    )

    assert response.status_code == 200
    prompt_override = captured["prompt_override"]
    assert "parallel_tool_calls=true" in prompt_override
    assert "batch independent read-only inspection tool calls" in prompt_override
    assert "tool_choice=required" in prompt_override
    assert "must emit at least one tool_call" in prompt_override



def test_agent_prompt_marks_write_required_requests(monkeypatch):
    captured = {}

    def fake_complete_chat_turn(**kwargs):
        captured["prompt_override"] = kwargs.get("prompt_override")
        return (
            """
<tool_call>
<name>write</name>
<arguments>
<path>app/smoke_server.py</path>
</arguments>
</tool_call>
<write_content>
```python
print(\"smoke ok\")
```
</write_content>
""",
            "conv-test",
        )

    monkeypatch.setattr(router_module, "complete_chat_turn", fake_complete_chat_turn)

    client = make_client()
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "stream": False,
            "messages": [{"role": "user", "content": 'Create app/smoke_server.py. Use write. The file content must be exactly:\nprint("smoke ok")'}],
            "tools": [
                {
                    "type": "function",
                    "function": {"name": "write", "description": "Write file", "parameters": {}},
                }
            ],
        },
    )

    assert response.status_code == 200
    prompt_override = captured["prompt_override"]
    assert "Request classification: write_required." in prompt_override
    assert "Emit exactly one write tool_call on this turn." in prompt_override
    assert "Do not answer with prose or claim you lack tool access." in prompt_override
    assert "exactly one fenced code block inside <write_content>" in prompt_override



def test_agent_retries_tool_access_refusal_with_stronger_write_prompt(monkeypatch):
    calls = []

    def fake_complete_chat_turn(**kwargs):
        calls.append(("turn", kwargs))
        return (
            "I don't have access to the pi write tool in this chat, so I can't create app/smoke_server.py in your local workspace here.",
            "conv-test",
        )

    def fake_complete_chat(**kwargs):
        calls.append(("recovery", kwargs))
        return (
            """
<tool_call>
<name>write</name>
<arguments>
<path>app/smoke_server.py</path>
</arguments>
</tool_call>
<write_content>
```python
print(\"smoke ok\")
```
</write_content>
"""
        )

    monkeypatch.setattr(router_module, "complete_chat_turn", fake_complete_chat_turn)
    monkeypatch.setattr(router_module, "complete_chat", fake_complete_chat)

    client = make_client()
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "stream": False,
            "messages": [{"role": "user", "content": 'Create app/smoke_server.py. Use write. The file content must be exactly:\nprint("smoke ok")'}],
            "tools": [
                {
                    "type": "function",
                    "function": {"name": "write", "description": "Write file", "parameters": {}},
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["choices"][0]["finish_reason"] == "tool_calls"
    assert any(kind == "recovery" for kind, _kwargs in calls)
    recovery_prompt = [kwargs["prompt_override"] for kind, kwargs in calls if kind == "recovery"][0]
    assert "Recovery rule:" in recovery_prompt
    assert "The current task requires the write tool." in recovery_prompt
    assert "exactly one fenced code block inside <write_content>" in recovery_prompt



def test_write_required_prompt_is_not_reapplied_after_tool_result(monkeypatch):
    captured = {}

    def fake_complete_chat_turn(**kwargs):
        captured["prompt_override"] = kwargs.get("prompt_override")
        return ("<final_response>write done.</final_response>", "conv-test")

    monkeypatch.setattr(router_module, "complete_chat_turn", fake_complete_chat_turn)

    client = make_client()
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "stream": False,
            "messages": [
                {"role": "user", "content": 'Create app/smoke_server.py. Use write. The file content must be exactly:\nprint("smoke ok")'},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_test",
                            "type": "function",
                            "function": {
                                "name": "write",
                                "arguments": '{"path":"app/smoke_server.py","content":"print(\\"smoke ok\\")\\n"}',
                            },
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_test", "content": "wrote app/smoke_server.py"},
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {"name": "write", "description": "Write file", "parameters": {}},
                }
            ],
        },
    )

    assert response.status_code == 200
    prompt_override = captured["prompt_override"]
    assert "Request classification: write_required." not in prompt_override
    assert "Emit exactly one write tool_call on this turn." not in prompt_override
