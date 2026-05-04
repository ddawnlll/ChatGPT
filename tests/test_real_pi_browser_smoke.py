from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
import uvicorn

from proxy.app.main import create_app
from proxy.app.state import conversation_store

pytestmark = pytest.mark.browser_e2e

PI_BINARY = "pi"
PROVIDER_NAME = "chatgpt-wrapper"
MODEL_ID = "chatgpt-playwright"


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def running_live_proxy_server():
    conversation_store.clear()
    port = _find_free_port()
    app = create_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 15
    while time.time() < deadline:
        if getattr(server, "started", False):
            break
        time.sleep(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=5)
        raise RuntimeError("Live proxy server did not start")

    try:
        yield f"http://127.0.0.1:{port}/v1"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        conversation_store.clear()


def write_pi_models_json(agent_dir: Path, base_url: str) -> None:
    agent_dir.mkdir(parents=True, exist_ok=True)
    models = {
        "providers": {
            PROVIDER_NAME: {
                "baseUrl": base_url,
                "api": "openai-completions",
                "apiKey": "dummy",
                "compat": {
                    "supportsDeveloperRole": False,
                    "supportsReasoningEffort": False,
                },
                "models": [
                    {
                        "id": MODEL_ID,
                        "name": "ChatGPT Playwright",
                        "reasoning": True,
                        "input": ["text"],
                        "contextWindow": 128000,
                        "maxTokens": 16384,
                        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                    }
                ],
            }
        }
    }
    (agent_dir / "models.json").write_text(json.dumps(models), encoding="utf-8")


def run_pi(agent_dir: Path, cwd: Path, prompt: str, *, tools: str | None = None) -> subprocess.CompletedProcess[str]:
    command = [
        PI_BINARY,
        "--provider",
        PROVIDER_NAME,
        "--model",
        MODEL_ID,
        "--print",
        "--no-session",
        "--offline",
        "--no-extensions",
        "--no-skills",
        "--no-prompt-templates",
        "--no-context-files",
        "--mode",
        "text",
    ]
    if tools:
        command.extend(["--tools", tools])
    command.append(prompt)

    env = {**os.environ, "PI_CODING_AGENT_DIR": str(agent_dir), "RUN_BROWSER_E2E": "1"}
    return subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, timeout=120)


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_E2E") != "1", reason="set RUN_BROWSER_E2E=1 to run real browser smoke tests")
@pytest.mark.skipif(not shutil.which(PI_BINARY), reason="pi binary is required for live pi/browser smoke tests")
def test_real_pi_cli_browser_final_response_smoke(tmp_path):
    with running_live_proxy_server() as base_url:
        agent_dir = tmp_path / "pi-agent"
        write_pi_models_json(agent_dir, base_url)
        result = run_pi(
            agent_dir,
            tmp_path,
            "Reply with plain text only: Ready. No markdown, no code fences, no tags.",
        )

    assert result.returncode == 0, result.stderr
    assert "Ready" in result.stdout


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_E2E") != "1", reason="set RUN_BROWSER_E2E=1 to run real browser smoke tests")
@pytest.mark.skipif(not shutil.which(PI_BINARY), reason="pi binary is required for live pi/browser smoke tests")
def test_real_pi_cli_browser_write_smoke(tmp_path):
    with running_live_proxy_server() as base_url:
        agent_dir = tmp_path / "pi-agent"
        write_pi_models_json(agent_dir, base_url)
        result = run_pi(
            agent_dir,
            tmp_path,
            "Create app/live_pi_smoke.py using write. Put exactly this file content: print(\"live pi smoke\")",
            tools="write",
        )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "app" / "live_pi_smoke.py").read_text(encoding="utf-8") == 'print("live pi smoke")\n'
    assert "Created app/live_pi_smoke.py." in result.stdout or "live_pi_smoke.py" in result.stdout
