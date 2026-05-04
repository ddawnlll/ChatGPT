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
from typing import Any, Callable

import pytest
import uvicorn

from proxy.app import router as router_module
from proxy.app.main import create_app
from proxy.app.state import conversation_store

PI_BINARY = "pi"
PROVIDER_NAME = "chatgpt-wrapper"
MODEL_ID = "chatgpt-playwright"


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def running_proxy_server(monkeypatch: pytest.MonkeyPatch, complete_chat_turn_impl: Callable[..., tuple[str, str | None]]):
    conversation_store.clear()
    monkeypatch.setattr(router_module, "complete_chat_turn", complete_chat_turn_impl)

    port = _find_free_port()
    app = create_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 10
    while time.time() < deadline:
        if getattr(server, "started", False):
            break
        time.sleep(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=5)
        raise RuntimeError("Proxy test server did not start")

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

    env = {**os.environ, "PI_CODING_AGENT_DIR": str(agent_dir)}
    return subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, timeout=60)


@pytest.mark.skipif(not shutil.which(PI_BINARY), reason="pi binary is required for CLI E2E tests")
def test_pi_cli_final_response_flow(monkeypatch, tmp_path):
    calls: list[list[dict[str, Any]]] = []

    def fake_complete_chat_turn(**kwargs):
        calls.append(kwargs["messages"])
        return ("<final_response>Ready.</final_response>", "conv-pi-final")

    with running_proxy_server(monkeypatch, fake_complete_chat_turn) as base_url:
        agent_dir = tmp_path / "pi-agent"
        write_pi_models_json(agent_dir, base_url)
        result = run_pi(agent_dir, tmp_path, "Reply exactly Ready.")

    assert result.returncode == 0, result.stderr
    assert "Ready." in result.stdout
    assert len(calls) >= 1


@pytest.mark.skipif(not shutil.which(PI_BINARY), reason="pi binary is required for CLI E2E tests")
@pytest.mark.parametrize(
    ("tool_name", "tool_args", "allowed_tools", "setup", "assertion"),
    [
        (
            "read",
            {"path": "sample.txt"},
            "read",
            lambda cwd: (cwd / "sample.txt").write_text("alpha\n", encoding="utf-8"),
            lambda cwd, messages: any(message.get("role") == "tool" and "alpha" in str(message.get("content", "")) for message in messages),
        ),
        (
            "write",
            {"path": "created.txt", "content": "hello from pi\n"},
            "write",
            lambda cwd: None,
            lambda cwd, messages: (cwd / "created.txt").read_text(encoding="utf-8") == "hello from pi\n",
        ),
        (
            "edit",
            {"path": "edit.txt", "edits": [{"oldText": "before", "newText": "after"}]},
            "edit",
            lambda cwd: (cwd / "edit.txt").write_text("before\n", encoding="utf-8"),
            lambda cwd, messages: (cwd / "edit.txt").read_text(encoding="utf-8") == "after\n",
        ),
        (
            "bash",
            {"command": "printf 'ok-from-bash' > bash_out.txt"},
            "bash",
            lambda cwd: None,
            lambda cwd, messages: (cwd / "bash_out.txt").read_text(encoding="utf-8") == "ok-from-bash",
        ),
        (
            "grep",
            {"pattern": "needle", "path": "."},
            "grep",
            lambda cwd: (cwd / "grep.txt").write_text("needle\n", encoding="utf-8"),
            lambda cwd, messages: any(message.get("role") == "tool" and "needle" in str(message.get("content", "")) for message in messages),
        ),
        (
            "find",
            {"path": ".", "pattern": "*.txt"},
            "find",
            lambda cwd: (cwd / "findme.txt").write_text("x\n", encoding="utf-8"),
            lambda cwd, messages: any(message.get("role") == "tool" and "findme.txt" in str(message.get("content", "")) for message in messages),
        ),
        (
            "ls",
            {"path": "."},
            "ls",
            lambda cwd: (cwd / "ls-visible.txt").write_text("x\n", encoding="utf-8"),
            lambda cwd, messages: any(message.get("role") == "tool" and "ls-visible.txt" in str(message.get("content", "")) for message in messages),
        ),
    ],
)
def test_pi_cli_tool_loop_executes_real_pi_tools(monkeypatch, tmp_path, tool_name, tool_args, allowed_tools, setup, assertion):
    setup(tmp_path)
    requests: list[list[dict[str, Any]]] = []

    def fake_complete_chat_turn(**kwargs):
        messages = kwargs["messages"]
        requests.append(messages)
        if any(message.get("role") == "tool" for message in messages):
            return (f"<final_response>{tool_name} done.</final_response>", f"conv-{tool_name}")
        return (f'<tool_call>{{"name":"{tool_name}","arguments":{json.dumps(tool_args, separators=(",", ":"))}}}</tool_call>', f"conv-{tool_name}")

    with running_proxy_server(monkeypatch, fake_complete_chat_turn) as base_url:
        agent_dir = tmp_path / "pi-agent"
        write_pi_models_json(agent_dir, base_url)
        result = run_pi(agent_dir, tmp_path, f"Use the {tool_name} tool.", tools=allowed_tools)

    assert result.returncode == 0, result.stderr
    assert f"{tool_name} done." in result.stdout
    assert len(requests) >= 2
    assert assertion(tmp_path, requests[-1]), result.stdout
    assert any(message.get("role") == "tool" for message in requests[-1])
