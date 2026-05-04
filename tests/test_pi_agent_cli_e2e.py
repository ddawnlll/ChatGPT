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
def running_proxy_server(
    monkeypatch: pytest.MonkeyPatch,
    complete_chat_turn_impl: Callable[..., tuple[str, str | None]],
    *,
    complete_chat_impl: Callable[..., str] | None = None,
):
    conversation_store.clear()
    monkeypatch.setattr(router_module, "complete_chat_turn", complete_chat_turn_impl)
    if complete_chat_impl is not None:
        monkeypatch.setattr(router_module, "complete_chat", complete_chat_impl)

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
def test_pi_cli_rejects_incomplete_final_response_tag(monkeypatch, tmp_path):
    def fake_complete_chat_turn(**kwargs):
        return ("<final", "conv-pi-bad-final")

    with running_proxy_server(monkeypatch, fake_complete_chat_turn) as base_url:
        agent_dir = tmp_path / "pi-agent"
        write_pi_models_json(agent_dir, base_url)
        result = run_pi(agent_dir, tmp_path, "Say hello.")

    assert result.returncode != 0
    combined = f"{result.stdout}\n{result.stderr}"
    assert "incomplete final_response tag" in combined or "malformed_tool_call" in combined


@pytest.mark.skipif(not shutil.which(PI_BINARY), reason="pi binary is required for CLI E2E tests")
def test_pi_cli_first_turn_malformed_tool_call_is_repaired_and_tool_executes(monkeypatch, tmp_path):
    requests: list[list[dict[str, Any]]] = []

    def fake_complete_chat_turn(**kwargs):
        messages = kwargs["messages"]
        requests.append(messages)
        if any(message.get("role") == "tool" for message in messages):
            return ("<final_response>read done.</final_response>", "conv-pi-repair")
        return ('<tool_call>{"name":"read","arguments":{"path":"sample.txt" "timeout":10}}</tool_call>', "conv-pi-repair")

    def fake_complete_chat(**kwargs):
        return """
<tool_call>
<name>read</name>
<arguments>
<path>sample.txt</path>
</arguments>
</tool_call>
"""

    (tmp_path / "sample.txt").write_text("alpha\n", encoding="utf-8")

    with running_proxy_server(monkeypatch, fake_complete_chat_turn, complete_chat_impl=fake_complete_chat) as base_url:
        agent_dir = tmp_path / "pi-agent"
        write_pi_models_json(agent_dir, base_url)
        result = run_pi(agent_dir, tmp_path, "Read sample.txt", tools="read")

    assert result.returncode == 0, result.stderr
    assert "read done." in result.stdout
    assert len(requests) >= 2
    assert any(message.get("role") == "tool" and "alpha" in str(message.get("content", "")) for message in requests[-1])


@pytest.mark.skipif(not shutil.which(PI_BINARY), reason="pi binary is required for CLI E2E tests")
def test_pi_cli_first_turn_partial_tool_tag_is_repaired_and_tool_executes(monkeypatch, tmp_path):
    requests: list[list[dict[str, Any]]] = []

    def fake_complete_chat_turn(**kwargs):
        messages = kwargs["messages"]
        requests.append(messages)
        if any(message.get("role") == "tool" for message in messages):
            return ("<final_response>read done.</final_response>", "conv-pi-partial")
        return ("<", "conv-pi-partial")

    def fake_complete_chat(**kwargs):
        return """
<tool_call>
<name>read</name>
<arguments>
<path>sample.txt</path>
</arguments>
</tool_call>
"""

    (tmp_path / "sample.txt").write_text("alpha\n", encoding="utf-8")

    with running_proxy_server(monkeypatch, fake_complete_chat_turn, complete_chat_impl=fake_complete_chat) as base_url:
        agent_dir = tmp_path / "pi-agent"
        write_pi_models_json(agent_dir, base_url)
        result = run_pi(agent_dir, tmp_path, "Read sample.txt", tools="read")

    assert result.returncode == 0, result.stderr
    assert "read done." in result.stdout
    assert len(requests) >= 2
    assert any(message.get("role") == "tool" and "alpha" in str(message.get("content", "")) for message in requests[-1])


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
    if tool_name == "write":
        assert "Created created.txt." in result.stdout
        assert len(requests) == 1
    elif tool_name == "edit":
        assert "Updated edit.txt." in result.stdout
        assert len(requests) == 1
    elif tool_name == "bash":
        assert "Command completed successfully." in result.stdout
        assert len(requests) == 1
    else:
        assert f"{tool_name} done." in result.stdout
        assert len(requests) >= 2
        assert any(message.get("role") == "tool" for message in requests[-1])
        assert assertion(tmp_path, requests[-1]), result.stdout
        return

    assert assertion(tmp_path, requests[0]), result.stdout


@pytest.mark.skipif(not shutil.which(PI_BINARY), reason="pi binary is required for CLI E2E tests")
def test_pi_cli_multi_tool_calls_execute_in_one_turn(monkeypatch, tmp_path):
    requests: list[list[dict[str, Any]]] = []
    (tmp_path / "sample.txt").write_text("alpha\n", encoding="utf-8")
    (tmp_path / "ls-visible.txt").write_text("x\n", encoding="utf-8")

    def fake_complete_chat_turn(**kwargs):
        messages = kwargs["messages"]
        requests.append(messages)
        tool_messages = [message for message in messages if message.get("role") == "tool"]
        if len(tool_messages) >= 2:
            return ("<final_response>batch done.</final_response>", "conv-pi-batch")
        return (
            """
<tool_call><name>read</name><arguments><path>sample.txt</path></arguments></tool_call>
<tool_call><name>ls</name><arguments><path>.</path></arguments></tool_call>
""",
            "conv-pi-batch",
        )

    with running_proxy_server(monkeypatch, fake_complete_chat_turn) as base_url:
        agent_dir = tmp_path / "pi-agent"
        write_pi_models_json(agent_dir, base_url)
        result = run_pi(agent_dir, tmp_path, "Read sample.txt and list the directory", tools="read,ls")

    assert result.returncode == 0, result.stderr
    assert "batch done." in result.stdout
    assert len(requests) >= 2
    tool_messages = [message for message in requests[-1] if message.get("role") == "tool"]
    assert len(tool_messages) >= 2
    rendered_tool_text = "\n".join(str(message.get("content", "")) for message in tool_messages)
    assert "alpha" in rendered_tool_text
    assert "ls-visible.txt" in rendered_tool_text


@pytest.mark.skipif(not shutil.which(PI_BINARY), reason="pi binary is required for CLI E2E tests")
def test_pi_cli_simple_write_fastpath_avoids_second_browser_prompt(monkeypatch, tmp_path):
    requests: list[list[dict[str, Any]]] = []

    def fake_complete_chat_turn(**kwargs):
        requests.append(kwargs["messages"])
        return ('<tool_call>{"name":"write","arguments":{"path":"created.txt","content":"hello from pi\\n"}}</tool_call>', "conv-write-fast")

    with running_proxy_server(monkeypatch, fake_complete_chat_turn) as base_url:
        agent_dir = tmp_path / "pi-agent"
        write_pi_models_json(agent_dir, base_url)
        result = run_pi(agent_dir, tmp_path, "Create created.txt", tools="write")

    assert result.returncode == 0, result.stderr
    assert "Created created.txt." in result.stdout
    assert len(requests) == 1


@pytest.mark.skipif(not shutil.which(PI_BINARY), reason="pi binary is required for CLI E2E tests")
def test_pi_cli_read_then_final_uses_one_post_tool_final_prompt(monkeypatch, tmp_path):
    requests: list[dict[str, Any]] = []
    (tmp_path / "sample.txt").write_text("alpha\n", encoding="utf-8")

    def fake_complete_chat_turn(**kwargs):
        requests.append(kwargs)
        messages = kwargs["messages"]
        if any(message.get("role") == "tool" for message in messages):
            return ("<final_response>sample says alpha.</final_response>", "conv-read-final")
        return ('<tool_call>{"name":"read","arguments":{"path":"sample.txt"}}</tool_call>', "conv-read-final")

    with running_proxy_server(monkeypatch, fake_complete_chat_turn) as base_url:
        agent_dir = tmp_path / "pi-agent"
        write_pi_models_json(agent_dir, base_url)
        result = run_pi(agent_dir, tmp_path, "Read sample.txt and summarize it", tools="read")

    assert result.returncode == 0, result.stderr
    assert "sample says alpha." in result.stdout
    assert len(requests) == 2
    assert "Do not call tools on this turn." in requests[-1]["prompt_override"]
    assert "Return exactly one <final_response>...</final_response> block" in requests[-1]["prompt_override"]


@pytest.mark.skipif(not shutil.which(PI_BINARY), reason="pi binary is required for CLI E2E tests")
def test_pi_cli_regression_multiturn_session_does_not_reuse_stale_write_fastpath(monkeypatch, tmp_path):
    requests: list[dict[str, Any]] = []
    phase = {"step": 0}

    def fake_complete_chat_turn(**kwargs):
        requests.append(kwargs)
        messages = kwargs["messages"]
        has_tool = any(message.get("role") == "tool" for message in messages)
        phase["step"] += 1
        step = phase["step"]

        if step == 1:
            return ("<final_response>Hello!</final_response>", "conv-regression")
        if step == 2:
            return ('<tool_call>{"name":"write","arguments":{"path":"app/server.py","content":"print(1)\\n"}}</tool_call>', "conv-regression")
        if step == 3:
            return ('<tool_call>{"name":"edit","arguments":{"path":"app/server.py","edits":[{"oldText":"print(1)","newText":"print(2)"}]}}</tool_call>', "conv-regression")
        if step == 4 and not has_tool:
            return ('<tool_call>{"name":"read","arguments":{"path":"app/server.py"}}</tool_call>', "conv-regression")
        if step == 5 and has_tool:
            return ("<final_response>Analysis done.</final_response>", "conv-regression")
        if step == 6:
            return ('<tool_call>{"name":"write","arguments":{"path":"docs/server.md","content":"# Server\\n"}}</tool_call>', "conv-regression")
        return ("<final_response>fallback</final_response>", "conv-regression")

    with running_proxy_server(monkeypatch, fake_complete_chat_turn) as base_url:
        agent_dir = tmp_path / "pi-agent"
        write_pi_models_json(agent_dir, base_url)
        result1 = run_pi(agent_dir, tmp_path, "hello")
        result2 = run_pi(agent_dir, tmp_path, "write app/server.py", tools="write")
        result3 = run_pi(agent_dir, tmp_path, "edit @app/server.py file for adding more stuff", tools="edit")
        result4 = run_pi(agent_dir, tmp_path, "read and analyze app/server.py", tools="read")
        result5 = run_pi(agent_dir, tmp_path, "create docs/server.md", tools="write")

    assert result1.returncode == 0 and "Hello!" in result1.stdout
    assert result2.returncode == 0 and "Created app/server.py." in result2.stdout
    assert result3.returncode == 0 and "Updated app/server.py." in result3.stdout
    assert result4.returncode == 0 and "Analysis done." in result4.stdout
    assert result5.returncode == 0 and "Created docs/server.md." in result5.stdout
    assert len(requests) == 6
    assert any("Do not call tools on this turn." in str(call.get("prompt_override", "")) for call in requests)
