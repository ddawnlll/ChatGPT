from __future__ import annotations

import json
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from proxy.app.main import create_app
from proxy.app.tools_shim import parse_assistant_action

pytestmark = pytest.mark.browser_e2e

PI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": f"Tool {name}",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "command": {"type": "string"}, "pattern": {"type": "string"}}, "required": []},
        },
    }
    for name in ["read", "write", "edit", "bash", "grep", "find", "ls"]
]


@pytest.fixture
def browser_client():
    return TestClient(create_app())


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_E2E") != "1", reason="set RUN_BROWSER_E2E=1 to run real browser smoke tests")
def test_real_browser_write_tool_call_preserves_write_content(browser_client: TestClient):
    user_id = f"browser-write-smoke-{uuid4().hex}"
    prompt = 'Create app/smoke_server.py. Use write. The file content must be exactly:\nprint("smoke ok")'

    last_choice = None
    last_debug = None
    for _ in range(3):
        response = browser_client.post(
            "/v1/chat/completions",
            json={
                "model": "chatgpt-playwright",
                "user": user_id,
                "messages": [{"role": "user", "content": prompt}],
                "tools": PI_TOOLS,
            },
        )

        assert response.status_code == 200, response.text
        choice = response.json()["choices"][0]
        last_choice = choice

        if choice["finish_reason"] == "tool_calls":
            tool_call = choice["message"]["tool_calls"][0]["function"]
            args = json.loads(tool_call["arguments"])
            last_debug = {
                "finish_reason": choice.get("finish_reason"),
                "tool_name": tool_call.get("name"),
                "has_path": "path" in args,
                "has_content": "content" in args,
                "path": args.get("path"),
                "content_preview": (args.get("content") or "")[:120],
                "raw_response_preview": json.dumps(choice, ensure_ascii=False)[:400],
            }
            assert tool_call["name"] == "write"
            assert args["path"] == "app/smoke_server.py"
            assert args["content"] == 'print("smoke ok")\n'
            return

        content = choice["message"].get("content") or ""
        action = parse_assistant_action(content)
        last_debug = {
            "finish_reason": choice.get("finish_reason"),
            "action_kind": action.kind,
            "tool_name": getattr(action, "tool_name", None),
            "has_path": bool(getattr(action, "tool_arguments", None) and "path" in action.tool_arguments),
            "has_content": bool(getattr(action, "tool_arguments", None) and "content" in action.tool_arguments),
            "path": getattr(action, "tool_arguments", {}).get("path") if getattr(action, "tool_arguments", None) else None,
            "content_preview": ((getattr(action, "tool_arguments", {}) or {}).get("content") or "")[:120],
            "raw_response_preview": content[:400],
        }
        if action.kind == "tool" and action.tool_name == "write":
            assert action.tool_arguments is not None
            assert action.tool_arguments["path"] == "app/smoke_server.py"
            assert action.tool_arguments["content"] == 'print("smoke ok")\n'
            return

    raise AssertionError(
        "expected write tool call with content; "
        f"debug={json.dumps(last_debug, ensure_ascii=False)}; "
        f"choice_preview={json.dumps(last_choice, ensure_ascii=False)[:400]}"
    )
