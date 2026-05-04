import pytest


def test_fake_playwright_daemon_streams_chunks_and_stores_result(monkeypatch, playwright_transport, daemon_events):
    transport = playwright_transport

    monkeypatch.setattr(
        transport,
        "_run",
        lambda message, image=None, new_conversation=True: daemon_events(
            {"type": "status", "stage": "sending_prompt"},
            {"type": "chunk", "content": "Re"},
            {"type": "chunk", "content": "ady."},
            {
                "type": "result",
                "success": True,
                "text": "Ready.",
                "remote_conversation_id": "conv-1",
                "remote_parent_message_id": "msg-1",
                "transport_details": {"last_stage": "result_ready"},
                "verification_hints": {"remote_conversation_exists": True},
            },
        ),
    )

    chunks = list(transport.stream_message("hello"))

    assert chunks == ["Re", "ady."]
    result = transport.get_last_result()
    assert result.text == "Ready."
    assert result.remote_conversation_id == "conv-1"


def test_fake_playwright_daemon_failed_result_raises_runtime_error(monkeypatch, playwright_transport, daemon_events):
    transport = playwright_transport

    monkeypatch.setattr(
        transport,
        "_run",
        lambda message, image=None, new_conversation=True: daemon_events(
            {"type": "status", "stage": "request_received"},
            {"type": "result", "success": False, "error": "No assistant text was captured from the ChatGPT page"},
        ),
    )

    with pytest.raises(RuntimeError, match="No assistant text was captured"):
        transport.send_message("hello")


def test_fake_playwright_daemon_replace_event_is_ignored_for_streaming(monkeypatch, playwright_transport, daemon_events):
    transport = playwright_transport

    monkeypatch.setattr(
        transport,
        "_run",
        lambda message, image=None, new_conversation=True: daemon_events(
            {"type": "status", "stage": "assistant_text_updated"},
            {"type": "replace", "content": "Ready."},
            {
                "type": "result",
                "success": True,
                "text": "Ready.",
                "remote_conversation_id": "conv-2",
                "remote_parent_message_id": "msg-2",
                "transport_details": {},
                "verification_hints": {},
            },
        ),
    )

    chunks = list(transport.stream_message("hello"))
    assert chunks == []
    assert transport.get_last_result().text == "Ready."


def test_fake_playwright_daemon_missing_result_raises_clean_error(monkeypatch, playwright_transport, daemon_events):
    transport = playwright_transport

    monkeypatch.setattr(
        transport,
        "_run",
        lambda message, image=None, new_conversation=True: daemon_events(
            {"type": "status", "stage": "request_received"},
            {"type": "error", "stage": "request_failed", "message": "browser closed"},
        ),
    )

    with pytest.raises(RuntimeError, match="did not emit a final result event"):
        transport.send_message("hello")

    assert transport.request_diagnostics["last_stage"] == "request_failed"
    assert transport.request_diagnostics["playwright_error"] == "browser closed"
