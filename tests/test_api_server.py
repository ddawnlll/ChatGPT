import pytest
from fastapi.testclient import TestClient

import api_server
from transport_runtime import TransportResult


class DummyChatClient:
    def __init__(self):
        self.response = ""
        self.calls = []
        self.data = {"conversation_id": None, "parent_message_id": None}

    def get_session_status(self):
        return {"transport_mode": "anon", "bootstrap_ready": True}

    def get_debug_summary(self):
        return {"request_diagnostics": {"selected_transport_mode": "anon"}}

    def get_transport_audit(self):
        return {"anon_endpoints": {"conversation": "https://chatgpt.com/backend-anon/f/conversation"}}

    def _result(self):
        return TransportResult(
            text=self.response,
            remote_conversation_id=self.data.get("conversation_id"),
            remote_parent_message_id=self.data.get("parent_message_id"),
            transport_details={"selected_transport_mode": "anon"},
            verification_hints={"remote_conversation_exists": bool(self.data.get("conversation_id"))},
        )

    def send_message(self, message, image=None, *, new_conversation=True):
        if new_conversation or image:
            self.calls.append(("ask_question", message, image))
            self.data["conversation_id"] = "conv-1"
            self.data["parent_message_id"] = f"parent-{len(self.calls)}"
            self.response = f"answer:{message}"
        else:
            self.calls.append(("hold_conversation", message, False))
            self.data["parent_message_id"] = f"parent-{len(self.calls)}"
            self.response = f"continued:{message}"
        return self._result()

    def stream_message(self, message, image=None, *, new_conversation=True):
        result = self.send_message(message, image, new_conversation=new_conversation)
        midpoint = max(1, len(result.text) // 2)
        yield result.text[:midpoint]
        yield result.text[midpoint:]

    def get_last_result(self):
        return self._result()


@pytest.fixture(autouse=True)
def clear_session_store():
    api_server.init_db()
    api_server.clear_persistent_storage()
    api_server.SESSION_STORE.clear()
    api_server.CHAT_STORE.clear()
    api_server.CHAT_CLIENTS.clear()
    yield
    api_server.clear_persistent_storage()
    api_server.SESSION_STORE.clear()
    api_server.CHAT_STORE.clear()
    api_server.CHAT_CLIENTS.clear()


@pytest.mark.parametrize("thinking_mode", ["instant", "extended", "pro", "Instant", "  PRO  "])
def test_normalize_thinking_mode_accepts_valid_modes(thinking_mode):
    assert api_server.normalize_thinking_mode(thinking_mode) in {"instant", "extended", "pro"}


def test_normalize_cookies_accepts_string_and_cookie_list():
    assert api_server.normalize_cookies("a=b; c=d") == {"a": "b", "c": "d"}

    request = api_server.ConversationRequest(
        message="hello",
        session_id="session-1",
        cookies=[{"name": "session", "value": "token"}],
    )
    assert api_server.normalize_cookies(request.cookies) == {"session": "token"}


def test_resolve_session_material_stores_and_reuses_session_state():
    request_1 = api_server.ConversationRequest(
        message="hello",
        session_id="session-1",
        cookies=[{"name": "session", "value": "token"}],
        authorization="Bearer abc",
        thinking_mode="extended",
        model_name="generic-model-id",
        endpoint_overrides={"conversation": "https://chatgpt.com/backend-api/conversation"},
        extra_headers={"x-test": "1"},
    )

    resolved_1 = api_server.resolve_session_material(request_1)
    assert resolved_1["session_id"] == "session-1"
    assert resolved_1["cookies"] == {"session": "token"}
    assert resolved_1["authorization"] == "Bearer abc"
    assert resolved_1["thinking_mode"] == "extended"
    assert resolved_1["model_name"] == "generic-model-id"
    assert resolved_1["transport_mode"] == "authenticated"
    assert resolved_1["allow_anon_fallback"] is False
    assert resolved_1["endpoint_overrides"]["conversation"] == "https://chatgpt.com/backend-api/conversation"
    assert resolved_1["extra_headers"]["x-test"] == "1"

    request_2 = api_server.ConversationRequest(
        message="hello again",
        session_id="session-1",
    )

    resolved_2 = api_server.resolve_session_material(request_2)
    assert resolved_2["cookies"] == {"session": "token"}
    assert resolved_2["authorization"] == "Bearer abc"
    assert resolved_2["thinking_mode"] == "extended"
    assert resolved_2["model_name"] == "generic-model-id"
    assert resolved_2["transport_mode"] == "authenticated"
    assert resolved_2["allow_anon_fallback"] is False
    assert resolved_2["endpoint_overrides"]["conversation"] == "https://chatgpt.com/backend-api/conversation"
    assert resolved_2["extra_headers"]["x-test"] == "1"


def test_resolve_session_material_rejects_invalid_thinking_mode():
    request = api_server.ConversationRequest(
        message="hello",
        thinking_mode="unsupported",
    )

    with pytest.raises(api_server.HTTPException):
        api_server.resolve_session_material(request)


def test_resolve_session_material_accepts_playwright_browser_fields():
    request = api_server.ConversationRequest(
        message="hello",
        transport_mode="playwright",
        browser_user_data_dir="/tmp/chromium",
        browser_profile_directory="Default",
        browser_executable_path="/usr/bin/chromium",
        browser_channel="chromium",
        browser_headless=True,
        browser_chat_url="https://chatgpt.com/",
        browser_capture_timeout_ms=12345,
        browser_connect_over_cdp=True,
        browser_cdp_url="http://127.0.0.1:9222",
        browser_auto_start_debug_browser=True,
        browser_debugging_port=9222,
    )

    resolved = api_server.resolve_session_material(request)
    assert resolved["transport_mode"] == "playwright"
    assert resolved["browser_user_data_dir"] == "/tmp/chromium"
    assert resolved["browser_profile_directory"] == "Default"
    assert resolved["browser_executable_path"] == "/usr/bin/chromium"
    assert resolved["browser_channel"] == "chromium"
    assert resolved["browser_headless"] is True
    assert resolved["browser_chat_url"] == "https://chatgpt.com/"
    assert resolved["browser_capture_timeout_ms"] == 12345
    assert resolved["browser_connect_over_cdp"] is True
    assert resolved["browser_cdp_url"] == "http://127.0.0.1:9222"
    assert resolved["browser_auto_start_debug_browser"] is True
    assert resolved["browser_debugging_port"] == 9222


def test_resolve_session_material_accepts_model_name_without_session_id():
    request = api_server.ConversationRequest(
        message="hello",
        model_name="generic-model-id",
    )

    resolved = api_server.resolve_session_material(request)
    assert resolved["model_name"] == "generic-model-id"
    assert resolved["thinking_mode"] == "instant"
    assert resolved["transport_mode"] == "authenticated"
    assert resolved["allow_anon_fallback"] is False


def test_chat_endpoints_create_list_get_and_send(monkeypatch):
    dummy_client = DummyChatClient()
    monkeypatch.setattr(api_server, "build_client", lambda session_material: dummy_client)

    client = TestClient(api_server.app)

    create_response = client.post(
        "/chats",
        json={
            "title": "Test chat",
            "session_id": "session-1",
            "cookies": [{"name": "session", "value": "token"}],
            "authorization": "Bearer abc",
            "thinking_mode": "extended",
            "model_name": "generic-model-id",
            "transport_mode": "anon",
        },
    )
    assert create_response.status_code == 200
    chat = create_response.json()
    chat_id = chat["id"]
    assert chat["title"] == "Test chat"
    assert chat["thinking_mode"] == "extended"
    assert chat["model_name"] == "generic-model-id"
    assert chat["transport_mode"] == "anon"
    assert chat["allow_anon_fallback"] is False

    list_response = client.get("/chats")
    assert list_response.status_code == 200
    assert list_response.json()[0]["id"] == chat_id

    first_message = client.post(f"/chats/{chat_id}/messages", json={"message": "hello"})
    assert first_message.status_code == 200
    first_payload = first_message.json()
    assert first_payload["messages"][0]["role"] == "user"
    assert first_payload["messages"][1]["role"] == "assistant"
    assert first_payload["messages"][1]["content"] == "answer:hello"
    assert first_payload["verification"]["remote_conversation_exists"] is True
    assert first_payload["last_transport_diagnostics"]["selected_transport_mode"] == "anon"
    assert dummy_client.calls[0] == ("ask_question", "hello", None)

    second_message = client.post(f"/chats/{chat_id}/messages", json={"message": "again"})
    assert second_message.status_code == 200
    second_payload = second_message.json()
    assert second_payload["messages"][-1]["content"] == "continued:again"
    assert dummy_client.calls[1] == ("hold_conversation", "again", False)

    rename_response = client.patch(f"/chats/{chat_id}", json={"title": "Renamed chat"})
    assert rename_response.status_code == 200
    assert rename_response.json()["title"] == "Renamed chat"

    detail_response = client.get(f"/chats/{chat_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["id"] == chat_id
    assert detail["title"] == "Renamed chat"
    assert len(detail["messages"]) == 4

    delete_response = client.delete(f"/chats/{chat_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "success"

    missing_response = client.get(f"/chats/{chat_id}")
    assert missing_response.status_code == 404


def test_debug_transport_endpoint_returns_client_diagnostics(monkeypatch):
    dummy_client = DummyChatClient()
    monkeypatch.setattr(api_server, "build_client", lambda session_material: dummy_client)
    client = TestClient(api_server.app)

    create_response = client.post(
        "/chats",
        json={
            "title": "Debug chat",
            "session_id": "session-debug",
            "cookies": [{"name": "session", "value": "token"}],
            "authorization": "Bearer abc",
            "transport_mode": "anon",
        },
    )
    chat_id = create_response.json()["id"]

    response = client.get(f"/debug/transports/{chat_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["chat_id"] == chat_id
    assert payload["transport_mode"] == "anon"
    assert payload["verification"]["history_verification"] == "not_checked"
    assert payload["debug_summary"]["request_diagnostics"]["selected_transport_mode"] == "anon"


def test_verification_endpoint_updates_history_sidebar_and_notes(monkeypatch):
    dummy_client = DummyChatClient()
    monkeypatch.setattr(api_server, "build_client", lambda session_material: dummy_client)
    client = TestClient(api_server.app)

    create_response = client.post(
        "/chats",
        json={
            "title": "Verify chat",
            "session_id": "session-verify",
            "cookies": [{"name": "session", "value": "token"}],
            "authorization": "Bearer abc",
            "transport_mode": "authenticated",
        },
    )
    chat_id = create_response.json()["id"]

    response = client.patch(
        f"/chats/{chat_id}/verification",
        json={
            "history_verification": "failed",
            "sidebar_visible": False,
            "title_verification": "not_checked",
            "missing_browser_stage": "sidebar sync request",
            "notes": "chat answered but did not appear in sidebar",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["verification"]["history_verification"] == "failed"
    assert payload["verification"]["sidebar_visible"] is False
    assert payload["verification"]["missing_browser_stage"] == "sidebar sync request"
    assert payload["verification"]["notes"] == "chat answered but did not appear in sidebar"


def test_load_chats_from_db_restores_persisted_chat(monkeypatch):
    dummy_client = DummyChatClient()
    monkeypatch.setattr(api_server, "build_client", lambda session_material: dummy_client)
    client = TestClient(api_server.app)

    create_response = client.post(
        "/chats",
        json={
            "title": "Persistent chat",
            "session_id": "session-2",
            "cookies": [{"name": "session", "value": "token"}],
            "authorization": "Bearer abc",
            "transport_mode": "anon",
        },
    )
    chat_id = create_response.json()["id"]
    client.post(f"/chats/{chat_id}/messages", json={"message": "persist me"})

    api_server.CHAT_STORE.clear()
    api_server.CHAT_CLIENTS.clear()
    api_server.SESSION_STORE.clear()
    api_server.load_chats_from_db()

    assert chat_id in api_server.CHAT_STORE
    restored = api_server.CHAT_STORE[chat_id]
    assert restored["title"] == "Persistent chat"
    assert len(restored["messages"]) == 2
    assert restored["messages"][0]["content"] == "persist me"
