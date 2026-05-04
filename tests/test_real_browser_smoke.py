from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from proxy.app.main import create_app

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
def test_real_browser_smoke_ready_response(browser_client):
    first = browser_client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "user": "browser-smoke-test",
            "messages": [{"role": "user", "content": "Reply exactly with <final_response>Ready.</final_response>"}],
            "tools": PI_TOOLS,
        },
    )

    assert first.status_code == 200
    payload = first.json()
    assert payload["choices"][0]["message"]["content"] == "Ready."

    second = browser_client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "user": "browser-smoke-test",
            "messages": [{"role": "user", "content": "Reply exactly with <final_response>Still ready.</final_response>"}],
            "tools": PI_TOOLS,
        },
    )

    assert second.status_code == 200
    assert second.json()["choices"][0]["message"]["content"] == "Still ready."


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_E2E") != "1", reason="set RUN_BROWSER_E2E=1 to run real browser smoke tests")
@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("Reply exactly with <final_response>Ready.</final_response>", "Ready."),
        ("Reply exactly with <final_response>Proxy browser ok.</final_response>", "Proxy browser ok."),
    ],
)
def test_real_browser_multiple_final_response_prompts(browser_client, prompt, expected):
    response = browser_client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "user": f"browser-final-{expected}",
            "messages": [{"role": "user", "content": prompt}],
            "tools": PI_TOOLS,
        },
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == expected


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_E2E") != "1", reason="set RUN_BROWSER_E2E=1 to run real browser smoke tests")
@pytest.mark.parametrize(
    ("prompt", "tool_name"),
    [
        ("Reply exactly with <tool_call>{\"name\":\"read\",\"arguments\":{\"path\":\"server.py\"}}</tool_call>", "read"),
        ("Reply exactly with <tool_call>{\"name\":\"ls\",\"arguments\":{\"path\":\".\"}}</tool_call>", "ls"),
    ],
)
def test_real_browser_tool_call_smoke(browser_client, prompt, tool_name):
    response = browser_client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "user": f"browser-tool-{tool_name}",
            "messages": [{"role": "user", "content": prompt}],
            "tools": PI_TOOLS,
        },
    )

    assert response.status_code == 200
    choice = response.json()["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"][0]["function"]["name"] == tool_name
