from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from proxy.app.main import create_app

pytestmark = pytest.mark.browser_e2e


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_E2E") != "1", reason="set RUN_BROWSER_E2E=1 to run real browser smoke tests")
def test_real_browser_smoke_ready_response():
    client = TestClient(create_app())

    first = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "user": "browser-smoke-test",
            "messages": [{"role": "user", "content": "Reply exactly with <final_response>Ready.</final_response>"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "read",
                        "description": "Read file",
                        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
                    },
                }
            ],
        },
    )

    assert first.status_code == 200
    payload = first.json()
    assert payload["choices"][0]["message"]["content"] == "Ready."

    second = client.post(
        "/v1/chat/completions",
        json={
            "model": "chatgpt-playwright",
            "user": "browser-smoke-test",
            "messages": [{"role": "user", "content": "Reply exactly with <final_response>Still ready.</final_response>"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "read",
                        "description": "Read file",
                        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
                    },
                }
            ],
        },
    )

    assert second.status_code == 200
    assert second.json()["choices"][0]["message"]["content"] == "Still ready."
