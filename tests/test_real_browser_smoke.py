from __future__ import annotations

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


def normalize_browser_smoke_text(text: str) -> str:
    cleaned = str(text or "").replace("```", "").strip()
    if cleaned.endswith("."):
        cleaned = cleaned[:-1]
    return cleaned.strip()


def request_browser_text(browser_client: TestClient, payload: dict, *, attempts: int = 2) -> tuple[str, object]:
    last_response = None
    for _ in range(attempts):
        response = browser_client.post("/v1/chat/completions", json=payload)
        last_response = response
        assert response.status_code == 200, response.text
        text = response.json()["choices"][0]["message"]["content"]
        normalized = normalize_browser_smoke_text(text)
        if normalized:
            return normalized, response
    assert last_response is not None
    return "", last_response


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_E2E") != "1", reason="set RUN_BROWSER_E2E=1 to run real browser smoke tests")
def test_real_browser_smoke_ready_response(browser_client):
    user_id = f"browser-smoke-test-{uuid4().hex}"
    first_text, _first_response = request_browser_text(
        browser_client,
        {
            "model": "chatgpt-playwright",
            "user": user_id,
            "messages": [{"role": "user", "content": "Reply with plain text only: Ready. No markdown, no code fences, no tags."}],
        },
        attempts=3,
    )
    assert first_text == "Ready"

    second_text, _second_response = request_browser_text(
        browser_client,
        {
            "model": "chatgpt-playwright",
            "user": user_id,
            "messages": [{"role": "user", "content": "Reply with plain text only: Still ready. No markdown, no code fences, no tags."}],
        },
        attempts=2,
    )
    assert second_text == "Still ready"


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_E2E") != "1", reason="set RUN_BROWSER_E2E=1 to run real browser smoke tests")
@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("Reply with plain text only: Ready. No markdown, no code fences, no tags.", "Ready."),
        ("Reply with plain text only: Proxy browser ok. No markdown, no code fences, no tags.", "Proxy browser ok."),
    ],
)
def test_real_browser_multiple_final_response_prompts(browser_client, prompt, expected):
    user_id = f"browser-final-{uuid4().hex}"
    text, _response = request_browser_text(
        browser_client,
        {
            "model": "chatgpt-playwright",
            "user": user_id,
            "messages": [{"role": "user", "content": prompt}],
        },
        attempts=3,
    )
    assert text == expected.rstrip('.')


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_E2E") != "1", reason="set RUN_BROWSER_E2E=1 to run real browser smoke tests")
@pytest.mark.parametrize(
    ("prompt", "tool_name"),
    [
        ("Reply exactly with <tool_call>{\"name\":\"ls\",\"arguments\":{\"path\":\".\"}}</tool_call>", "ls"),
    ],
)
def test_real_browser_tool_call_smoke(browser_client, prompt, tool_name):
    user_id = f"browser-tool-{tool_name}-{uuid4().hex}"
    last_choice = None
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

        assert response.status_code == 200
        choice = response.json()["choices"][0]
        last_choice = choice
        if choice["finish_reason"] == "tool_calls":
            assert choice["message"]["tool_calls"][0]["function"]["name"] == tool_name
            return
        content = choice["message"].get("content") or ""
        action = parse_assistant_action(content)
        if action.kind == "tool" and action.tool_name == tool_name:
            return

    raise AssertionError(f"expected tool call for {tool_name}, got: {last_choice}")
