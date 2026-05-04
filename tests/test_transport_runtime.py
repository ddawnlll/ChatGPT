from transport_runtime import ChatGPTTransport, PlaywrightTransport, TransportResult, build_transport


class BareChatGPTLike:
    def __init__(self):
        self.data = {"conversation_id": None, "parent_message_id": None}

    def get_debug_summary(self):
        return {"request_diagnostics": {"selected_transport_mode": "authenticated"}}

    def get_session_status(self):
        return {"transport_mode": "authenticated"}

    def get_transport_audit(self):
        return {"selected_transport_mode": "authenticated"}

    def ask_question(self, message, image=None):
        self.data["conversation_id"] = "conv-auth"
        self.data["parent_message_id"] = "msg-auth"
        self.response = f"answer:{message}"
        return self.response

    def hold_conversation(self, message, new=False):
        self.response = f"continued:{message}"

    def stream_question(self, message, image=None):
        self.response = f"answer:{message}"
        yield self.response

    def hold_conversation_stream(self, message):
        self.response = f"continued:{message}"
        yield self.response


def test_chatgpt_transport_tolerates_missing_initial_response_attribute():
    transport = ChatGPTTransport(BareChatGPTLike())
    assert transport.response == ""
    result = transport.send_message("hello")
    assert result.text == "answer:hello"
    assert result.remote_conversation_id == "conv-auth"


def test_build_transport_returns_playwright_transport_for_playwright_mode():
    transport = build_transport(
        {
            "transport_mode": "playwright",
            "browser_user_data_dir": "/tmp/profile",
            "browser_profile_directory": "Default",
            "browser_executable_path": "/usr/bin/chrome",
        }
    )

    assert isinstance(transport, PlaywrightTransport)
    assert transport.get_session_status()["transport_mode"] == "playwright"


def test_playwright_transport_send_message_consumes_jsonl_events(monkeypatch):
    transport = PlaywrightTransport(
        {
            "transport_mode": "playwright",
            "browser_user_data_dir": "/tmp/profile",
            "browser_profile_directory": "Default",
            "browser_executable_path": "/usr/bin/chrome",
        }
    )

    monkeypatch.setattr(
        transport,
        "_run",
        lambda message, image=None, new_conversation=True: iter(
            [
                {"type": "status", "stage": "ui_detected"},
                {
                    "type": "result",
                    "success": True,
                    "text": "playwright answer",
                    "remote_conversation_id": "conv-pw",
                    "remote_parent_message_id": "msg-pw",
                    "transport_details": {"last_stage": "done", "ui_logged_in_likely": True},
                    "verification_hints": {"remote_conversation_exists": True},
                },
            ]
        ),
    )

    result = transport.send_message("hello")

    assert isinstance(result, TransportResult)
    assert result.text == "playwright answer"
    assert result.remote_conversation_id == "conv-pw"
    assert result.transport_details["effective_transport_mode"] == "playwright"
    assert transport.response == "playwright answer"
    assert transport.data["conversation_id"] == "conv-pw"


def test_playwright_transport_stream_message_yields_chunks_and_stores_result(monkeypatch):
    transport = PlaywrightTransport({"transport_mode": "playwright", "browser_user_data_dir": "/tmp/profile"})

    monkeypatch.setattr(
        transport,
        "_run",
        lambda message, image=None, new_conversation=True: iter(
            [
                {"type": "status", "stage": "sending_prompt"},
                {"type": "chunk", "content": "play"},
                {"type": "chunk", "content": "wright"},
                {
                    "type": "result",
                    "success": True,
                    "text": "playwright",
                    "remote_conversation_id": "conv-stream",
                    "remote_parent_message_id": "msg-stream",
                    "transport_details": {"ui_logged_in_likely": True},
                    "verification_hints": {"remote_conversation_exists": True},
                },
            ]
        ),
    )

    chunks = list(transport.stream_message("hello"))

    assert chunks == ["play", "wright"]
    result = transport.get_last_result()
    assert result.text == "playwright"
    assert result.remote_parent_message_id == "msg-stream"



def test_playwright_transport_stream_message_yields_replace_events(monkeypatch):
    transport = PlaywrightTransport({"transport_mode": "playwright", "browser_user_data_dir": "/tmp/profile"})

    monkeypatch.setattr(
        transport,
        "_run",
        lambda message, image=None, new_conversation=True: iter(
            [
                {"type": "chunk", "content": "Think"},
                {"type": "replace", "content": "Ready."},
                {
                    "type": "result",
                    "success": True,
                    "text": "Ready.",
                    "remote_conversation_id": "conv-replace",
                    "remote_parent_message_id": "msg-replace",
                    "transport_details": {"ui_logged_in_likely": True},
                    "verification_hints": {"remote_conversation_exists": True},
                },
            ]
        ),
    )

    chunks = list(transport.stream_message("hello"))

    assert chunks == ["Think", "Ready."]
    result = transport.get_last_result()
    assert result.text == "Ready."
    assert result.remote_parent_message_id == "msg-replace"
