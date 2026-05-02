import pytest
from fastapi.testclient import TestClient

import api_server


class DummyChatClient:
    def __init__(self):
        self.response = ""
        self.calls = []
        self.data = {"conversation_id": None, "parent_message_id": None}

    def ask_question(self, message, image=None):
        self.calls.append(("ask_question", message, image))
        self.data["conversation_id"] = "conv-1"
        self.data["parent_message_id"] = f"parent-{len(self.calls)}"
        self.response = f"answer:{message}"
        return self.response

    def hold_conversation(self, message, new=False):
        self.calls.append(("hold_conversation", message, new))
        self.data["parent_message_id"] = f"parent-{len(self.calls)}"
        self.response = f"continued:{message}"


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
    )

    resolved_1 = api_server.resolve_session_material(request_1)
    assert resolved_1["session_id"] == "session-1"
    assert resolved_1["cookies"] == {"session": "token"}
    assert resolved_1["authorization"] == "Bearer abc"
    assert resolved_1["thinking_mode"] == "extended"
    assert resolved_1["model_name"] == "generic-model-id"

    request_2 = api_server.ConversationRequest(
        message="hello again",
        session_id="session-1",
    )

    resolved_2 = api_server.resolve_session_material(request_2)
    assert resolved_2["cookies"] == {"session": "token"}
    assert resolved_2["authorization"] == "Bearer abc"
    assert resolved_2["thinking_mode"] == "extended"
    assert resolved_2["model_name"] == "generic-model-id"


def test_resolve_session_material_rejects_invalid_thinking_mode():
    request = api_server.ConversationRequest(
        message="hello",
        thinking_mode="unsupported",
    )

    with pytest.raises(api_server.HTTPException):
        api_server.resolve_session_material(request)


def test_resolve_session_material_accepts_model_name_without_session_id():
    request = api_server.ConversationRequest(
        message="hello",
        model_name="generic-model-id",
    )

    resolved = api_server.resolve_session_material(request)
    assert resolved["model_name"] == "generic-model-id"
    assert resolved["thinking_mode"] == "instant"


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
        },
    )
    assert create_response.status_code == 200
    chat = create_response.json()
    chat_id = chat["id"]
    assert chat["title"] == "Test chat"
    assert chat["thinking_mode"] == "extended"
    assert chat["model_name"] == "generic-model-id"

    list_response = client.get("/chats")
    assert list_response.status_code == 200
    assert list_response.json()[0]["id"] == chat_id

    first_message = client.post(f"/chats/{chat_id}/messages", json={"message": "hello"})
    assert first_message.status_code == 200
    first_payload = first_message.json()
    assert first_payload["messages"][0]["role"] == "user"
    assert first_payload["messages"][1]["role"] == "assistant"
    assert first_payload["messages"][1]["content"] == "answer:hello"
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
