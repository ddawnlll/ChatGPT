import json

from fastapi.testclient import TestClient

from proxy.app import client as client_module
from proxy.app import router as router_module
from proxy.app.main import create_app
from proxy.app.state import ConversationState, conversation_store

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


class DummyTransport:
    def __init__(self, text="<final_response>Ready.</final_response>"):
        self.data = {"conversation_id": None, "parent_message_id": None}
        self.calls = []
        self.text = text

    def send_message(self, message, image=None, *, new_conversation=True):
        self.calls.append({"message": message, "new_conversation": new_conversation})
        from transport_runtime import TransportResult
        return TransportResult(
            text=self.text,
            remote_conversation_id="remote-next",
            remote_parent_message_id="msg-next",
            transport_details={},
            verification_hints={},
        )


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



def test_agent_edit_with_xml_edits_string_returns_valid_array(monkeypatch):
    def fake_complete_chat_turn(**kwargs):
        return (
            '<tool_call>{"name":"edit","arguments":{"path":"app/server4.py","edits":"<edit><oldText>PORT = 8000</oldText><newText>PORT = 8090</newText></edit>"}}</tool_call>',
            "conv-test",
        )

    monkeypatch.setattr(router_module, "complete_chat_turn", fake_complete_chat_turn)

    client = make_client()
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "stream": False,
            "messages": [{"role": "user", "content": "edit app/server4.py changing port to 8090"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "edit",
                        "description": "Edit file",
                        "parameters": {},
                    },
                }
            ],
        },
    )

    assert response.status_code == 200
    args = response.json()["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    assert json.loads(args) == {
        "path": "app/server4.py",
        "edits": [{"oldText": "PORT = 8000", "newText": "PORT = 8090"}],
    }



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
    def fail_complete_chat_turn(**kwargs):
        raise AssertionError("post-write turn should not reuse write-required planning prompt")

    monkeypatch.setattr(router_module, "complete_chat_turn", fail_complete_chat_turn)

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
    assert response.json()["choices"][0]["message"]["content"] == "Created app/smoke_server.py."



def test_router_stores_after_tools_plan_but_returns_only_tool_calls(monkeypatch):
    transport = DummyTransport(
        text="""
<tool_call>
<name>write</name>
<arguments>
<path>app/server.py</path>
</arguments>
</tool_call>
<write_content>
```python
print(1)
```
</write_content>
<after_tools>
<on_success>Created app/server.py.</on_success>
<on_failure>Could not create app/server.py: {error}</on_failure>
</after_tools>
"""
    )
    monkeypatch.setattr(client_module, "build_transport", lambda session_material: transport)

    client = make_client()
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "stream": False,
            "user": "conv-plan",
            "messages": [{"role": "user", "content": "Create app/server.py"}],
            "tools": [{"type": "function", "function": {"name": "write", "description": "Write file", "parameters": {}}}],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["choices"][0]["finish_reason"] == "tool_calls"
    assert payload["choices"][0]["message"]["content"] is None
    state = conversation_store.get("conv-plan")
    assert state is not None
    pending = state.data.get("pending_after_tools")
    assert isinstance(pending, dict)
    assert pending



def test_post_write_tool_result_uses_on_success_without_browser_call(monkeypatch):
    transport = DummyTransport(
        text="""
<tool_call>
<name>write</name>
<arguments>
<path>app/server.py</path>
</arguments>
</tool_call>
<write_content>
```python
print(1)
```
</write_content>
<after_tools>
<on_success>Created app/server.py.</on_success>
<on_failure>Could not create app/server.py: {error}</on_failure>
</after_tools>
"""
    )
    monkeypatch.setattr(client_module, "build_transport", lambda session_material: transport)

    client = make_client()
    first = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "stream": False,
            "user": "conv-plan",
            "messages": [{"role": "user", "content": "Create app/server.py"}],
            "tools": [{"type": "function", "function": {"name": "write", "description": "Write file", "parameters": {}}}],
        },
    )
    tool_call = first.json()["choices"][0]["message"]["tool_calls"][0]

    second = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "stream": False,
            "user": "conv-plan",
            "messages": [
                {"role": "user", "content": "Create app/server.py"},
                {"role": "assistant", "content": None, "tool_calls": [tool_call]},
                {"role": "tool", "tool_call_id": tool_call["id"], "content": "Successfully wrote 12 bytes"},
            ],
            "tools": [{"type": "function", "function": {"name": "write", "description": "Write file", "parameters": {}}}],
        },
    )

    assert second.status_code == 200
    assert second.json()["choices"][0]["message"]["content"] == "Created app/server.py."
    assert len(transport.calls) == 1



def test_post_write_tool_result_returns_local_final_without_browser_call(monkeypatch):
    def fail_complete_chat_turn(**kwargs):
        raise AssertionError("browser call should not happen for write fast-path")

    monkeypatch.setattr(router_module, "complete_chat_turn", fail_complete_chat_turn)

    client = make_client()
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "stream": False,
            "messages": [
                {"role": "user", "content": "Create app/server.py"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_write",
                            "type": "function",
                            "function": {"name": "write", "arguments": '{"path":"app/server.py","content":"print(1)\\n"}'},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_write", "content": "Successfully wrote 12 bytes"},
            ],
            "tools": [{"type": "function", "function": {"name": "write", "description": "Write file", "parameters": {}}}],
        },
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "Created app/server.py."



def test_post_edit_tool_result_returns_local_final_without_browser_call(monkeypatch):
    def fail_complete_chat_turn(**kwargs):
        raise AssertionError("browser call should not happen for edit fast-path")

    monkeypatch.setattr(router_module, "complete_chat_turn", fail_complete_chat_turn)

    client = make_client()
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "stream": False,
            "messages": [
                {"role": "user", "content": "Update app/server.py"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_edit",
                            "type": "function",
                            "function": {"name": "edit", "arguments": '{"path":"app/server.py","edits":[{"oldText":"a","newText":"b"}]}'},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_edit", "content": "Edited file successfully"},
            ],
            "tools": [{"type": "function", "function": {"name": "edit", "description": "Edit file", "parameters": {}}}],
        },
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "Updated app/server.py."



def test_post_write_tool_failure_uses_on_failure_without_browser_call(monkeypatch):
    transport = DummyTransport(
        text="""
<tool_call>
<name>write</name>
<arguments>
<path>app/server.py</path>
</arguments>
</tool_call>
<write_content>
```python
print(1)
```
</write_content>
<after_tools>
<on_success>Created app/server.py.</on_success>
<on_failure>Could not create app/server.py: {error}</on_failure>
</after_tools>
"""
    )
    monkeypatch.setattr(client_module, "build_transport", lambda session_material: transport)

    client = make_client()
    first = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "stream": False,
            "user": "conv-fail",
            "messages": [{"role": "user", "content": "Create app/server.py"}],
            "tools": [{"type": "function", "function": {"name": "write", "description": "Write file", "parameters": {}}}],
        },
    )
    tool_call = first.json()["choices"][0]["message"]["tool_calls"][0]

    second = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "stream": False,
            "user": "conv-fail",
            "messages": [
                {"role": "user", "content": "Create app/server.py"},
                {"role": "assistant", "content": None, "tool_calls": [tool_call]},
                {"role": "tool", "tool_call_id": tool_call["id"], "content": "Permission denied writing app/server.py"},
            ],
            "tools": [{"type": "function", "function": {"name": "write", "description": "Write file", "parameters": {}}}],
        },
    )

    assert second.status_code == 200
    assert "Could not create app/server.py" in second.json()["choices"][0]["message"]["content"]
    assert "Permission denied" in second.json()["choices"][0]["message"]["content"]
    assert len(transport.calls) == 1



def test_post_read_tool_result_uses_compact_final_only_prompt(monkeypatch):
    captured = {}

    def fake_complete_chat_turn(**kwargs):
        captured.update(kwargs)
        return ("<final_response>README summary.</final_response>", "conv-test")

    monkeypatch.setattr(router_module, "complete_chat_turn", fake_complete_chat_turn)

    client = make_client()
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "stream": False,
            "messages": [
                {"role": "user", "content": "Summarize README.md"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_read",
                            "type": "function",
                            "function": {"name": "read", "arguments": '{"path":"README.md"}'},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_read", "content": "README contents here"},
            ],
            "tools": [{"type": "function", "function": {"name": "read", "description": "Read file", "parameters": {}}}],
        },
    )

    assert response.status_code == 200
    prompt_override = captured["prompt_override"]
    assert captured["force_new_conversation"] is True
    assert "Do not call tools on this turn." in prompt_override
    assert "Return exactly one <final_response>...</final_response> block" in prompt_override
    assert "Available tools:" not in prompt_override
    assert "For write, always use this exact pattern" not in prompt_override



def test_post_tool_final_prompt_hint_is_forwarded(monkeypatch):
    conversation_store.clear()
    planning_transport = DummyTransport(
        text="""
<tool_call><name>read</name><arguments><path>README.md</path></arguments></tool_call>
<after_tools><final_prompt>Summarize the README in one sentence.</final_prompt></after_tools>
"""
    )
    monkeypatch.setattr(client_module, "build_transport", lambda session_material: planning_transport)

    planner = client_module.RuntimeClient("chatgpt-playwright")
    plan_text, _ = planner.complete_chat_turn(
        messages=[{"role": "user", "content": "Summarize README.md"}],
        conversation_id="conv-plan",
        prompt_override="plan prompt",
        force_new_conversation=True,
    )
    plan_action = router_module.parse_assistant_action(plan_text)
    tool_call = router_module.action_tool_calls(plan_action)[0]

    captured = {}

    def fake_complete_chat_turn(**kwargs):
        captured.update(kwargs)
        return ("<final_response>README summary.</final_response>", "conv-plan")

    monkeypatch.setattr(router_module, "complete_chat_turn", fake_complete_chat_turn)

    client = TestClient(create_app())
    second = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "stream": False,
            "user": "conv-plan",
            "messages": [
                {"role": "user", "content": "Summarize README.md"},
                {"role": "assistant", "content": None, "tool_calls": [tool_call]},
                {"role": "tool", "tool_call_id": tool_call["id"], "content": "README contents here"},
            ],
            "tools": [{"type": "function", "function": {"name": "read", "description": "Read file", "parameters": {}}}],
        },
    )

    assert second.status_code == 200
    assert "Additional finalization instruction:" in captured["prompt_override"]
    assert "Summarize the README in one sentence." in captured["prompt_override"]



def test_final_only_prompt_disallows_tool_calls(monkeypatch):
    def fake_complete_chat_turn(**kwargs):
        return ('<tool_call>{"name":"read","arguments":{"path":"README.md"}}</tool_call>', "conv-test")

    monkeypatch.setattr(router_module, "complete_chat_turn", fake_complete_chat_turn)

    client = make_client()
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "stream": False,
            "messages": [
                {"role": "user", "content": "Summarize README.md"},
                {"role": "assistant", "content": None, "tool_calls": [{"id": "call_read", "type": "function", "function": {"name": "read", "arguments": '{"path":"README.md"}'}}]},
                {"role": "tool", "tool_call_id": "call_read", "content": "README contents here"},
            ],
            "tools": [{"type": "function", "function": {"name": "read", "description": "Read file", "parameters": {}}}],
        },
    )

    assert response.status_code == 502
    assert "tool calls are not allowed after tool results" in response.json()["error"]["message"]



def test_old_write_tool_result_in_history_does_not_trigger_local_final_for_new_user_turn(monkeypatch):
    captured = {}

    def fake_complete_chat_turn(**kwargs):
        captured.update(kwargs)
        return ('<final_response>Hello!</final_response>', "conv-test")

    monkeypatch.setattr(router_module, "complete_chat_turn", fake_complete_chat_turn)

    client = make_client()
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "stream": False,
            "messages": [
                {"role": "user", "content": "Create server2.py"},
                {"role": "assistant", "content": None, "tool_calls": [{"id": "call_write", "type": "function", "function": {"name": "write", "arguments": '{"path":"server2.py","content":"print(1)\\n"}'}}]},
                {"role": "tool", "tool_call_id": "call_write", "content": "Successfully wrote 10 bytes"},
                {"role": "assistant", "content": "Created server2.py."},
                {"role": "user", "content": "hello!"},
            ],
            "tools": PI_TOOLS,
        },
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "Hello!"
    assert captured["force_new_conversation"] is True
    assert "Do not call tools on this turn." not in captured["prompt_override"]



def test_new_edit_request_after_previous_write_success_reenters_planning_mode(monkeypatch):
    captured = {}

    def fake_complete_chat_turn(**kwargs):
        captured.update(kwargs)
        return ('<tool_call>{"name":"edit","arguments":{"path":"app/server3.py","edits":[{"oldText":"a","newText":"b"}]}}</tool_call>', "conv-test")

    monkeypatch.setattr(router_module, "complete_chat_turn", fake_complete_chat_turn)

    client = make_client()
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "stream": False,
            "messages": [
                {"role": "user", "content": "write app/server3.py"},
                {"role": "assistant", "content": None, "tool_calls": [{"id": "call_write", "type": "function", "function": {"name": "write", "arguments": '{"path":"app/server3.py","content":"print(1)\\n"}'}}]},
                {"role": "tool", "tool_call_id": "call_write", "content": "Successfully wrote 10 bytes"},
                {"role": "assistant", "content": "Created app/server3.py."},
                {"role": "user", "content": "edit @app/server3.py file for adding more stuff"},
            ],
            "tools": [{"type": "function", "function": {"name": "edit", "description": "Edit file", "parameters": {}}}],
        },
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["finish_reason"] == "tool_calls"
    assert captured["force_new_conversation"] is True
    assert "Do not call tools on this turn." not in captured["prompt_override"]



def test_agent_planning_calls_use_force_new_conversation(monkeypatch):
    captured = {}

    def fake_complete_chat_turn(**kwargs):
        captured.update(kwargs)
        return ('<tool_call>{"name":"read","arguments":{"path":"server.py"}}</tool_call>', "conv-test")

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
    assert captured["force_new_conversation"] is True



def test_non_agent_calls_preserve_existing_conversation_behavior(monkeypatch):
    captured = {}

    def fake_complete_chat(**kwargs):
        captured.update(kwargs)
        return "Ready."

    monkeypatch.setattr(router_module, "complete_chat", fake_complete_chat)

    client = make_client()
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "stream": False,
            "user": "conv-plain",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 200
    assert captured["force_new_conversation"] is False
    assert captured["conversation_id"] == "conv-plain"



def test_runtime_client_force_new_conversation_uses_new_conversation_even_with_remote_state(monkeypatch):
    conversation_store.clear()
    state = ConversationState(conversation_id="conv-state", data={"remote_conversation_id": "remote-old", "remote_parent_message_id": "msg-old"})
    state.transport = DummyTransport()
    conversation_store.put(state)
    runtime = client_module.RuntimeClient("chatgpt-playwright")
    text, effective = runtime.complete_chat_turn(messages=[{"role": "user", "content": "hi"}], conversation_id="conv-state", force_new_conversation=True)

    assert text == "<final_response>Ready.</final_response>"
    assert effective == "conv-state"
    assert state.transport.calls[-1]["new_conversation"] is True
    assert state.transport.data["conversation_id"] is None
    assert state.transport.data["parent_message_id"] is None



def test_runtime_client_force_new_conversation_still_updates_aliases(monkeypatch):
    conversation_store.clear()
    transport = DummyTransport()
    monkeypatch.setattr(client_module, "build_transport", lambda session_material: transport)

    runtime = client_module.RuntimeClient("chatgpt-playwright")
    messages = [{"role": "user", "content": "hello"}]
    _text, effective = runtime.complete_chat_turn(messages=messages, force_new_conversation=True)

    assert effective is not None
    stored = conversation_store.get(effective)
    assert stored is not None
    assert stored.data["remote_conversation_id"] == "remote-next"
    assert conversation_store.count() == 1



def test_runtime_client_default_force_new_conversation_false_preserves_existing_behavior(monkeypatch):
    conversation_store.clear()
    state = ConversationState(conversation_id="conv-state", data={"remote_conversation_id": "remote-old", "remote_parent_message_id": "msg-old"})
    state.transport = DummyTransport()
    conversation_store.put(state)
    runtime = client_module.RuntimeClient("chatgpt-playwright")
    runtime.complete_chat_turn(messages=[{"role": "user", "content": "hi"}], conversation_id="conv-state", force_new_conversation=False)

    assert state.transport.calls[-1]["new_conversation"] is False
    assert state.transport.data["conversation_id"] == "remote-old"
    assert state.transport.data["parent_message_id"] == "msg-old"
