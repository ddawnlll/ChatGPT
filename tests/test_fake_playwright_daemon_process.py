from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "playwright_chat_transport.mjs"


def run_fake_daemon_request(request: dict) -> tuple[list[dict], str]:
    env = os.environ.copy()
    process = subprocess.Popen(
        ["bun", str(SCRIPT)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=ROOT,
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None

    process.stdin.write(json.dumps(request) + "\n")
    process.stdin.close()

    stdout = process.stdout.read()
    stderr = process.stderr.read()
    process.wait(timeout=15)

    events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    return events, stderr


def test_fake_daemon_process_emits_chunk_and_result_events():
    events, stderr = run_fake_daemon_request(
        {
            "message": "hello",
            "test_events": [
                {"type": "status", "stage": "request_received"},
                {"type": "chunk", "content": "Re"},
                {"type": "chunk", "content": "ady."},
                {"type": "result", "success": True, "text": "Ready.", "remote_conversation_id": "conv-proc"},
            ],
        }
    )

    assert stderr == ""
    assert events[0]["type"] == "status"
    chunks = [event for event in events if event.get("type") == "chunk"]
    assert chunks[0]["content"] == "Re"
    assert chunks[1]["content"] == "ady."
    assert events[-1]["type"] == "result"
    assert events[-1]["success"] is True
    assert events[-1]["text"] == "Ready."


def test_fake_daemon_process_emits_failed_result_cleanly():
    events, stderr = run_fake_daemon_request(
        {
            "message": "hello",
            "test_events": [
                {"type": "status", "stage": "request_received"},
                {"type": "result", "success": False, "error": "browser failed", "text": ""},
            ],
        }
    )

    assert stderr == ""
    assert events[-1]["type"] == "result"
    assert events[-1]["success"] is False
    assert events[-1]["error"] == "browser failed"


def test_fake_daemon_process_parse_error_returns_structured_result():
    env = os.environ.copy()
    process = subprocess.Popen(
        ["bun", str(SCRIPT)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=ROOT,
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None

    process.stdin.write("not-json\n")
    process.stdin.close()

    stdout = process.stdout.read()
    stderr = process.stderr.read()
    process.wait(timeout=15)

    assert stderr == ""
    events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    assert any(event.get("stage") == "request_parse_failed" for event in events if event.get("type") == "error")
    assert events[-1]["type"] == "result"
    assert events[-1]["success"] is False
    assert "JSON Parse error" in events[-1]["error"]
