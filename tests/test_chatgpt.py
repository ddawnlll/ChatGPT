import pytest
import wrapper.chatgpt as chatgpt_mod


class DummyResponse:
    def __init__(self, text: str, cookies=None, status_code: int = 200, json_data=None):
        self.text = text
        self.cookies = cookies or {}
        self.status_code = status_code
        self._json_data = json_data

    def json(self):
        if self._json_data is not None:
            return self._json_data
        return {}

    def iter_lines(self):
        for line in self.text.splitlines():
            yield line


def _patch_chatgpt_bootstrap(monkeypatch):
    monkeypatch.setattr(
        chatgpt_mod.IP_Info,
        "fetch_info",
        staticmethod(lambda session: ["1.2.3.4", "City", "Region", "0", "0", "UTC"]),
    )

    def fake_fetch_cookies(self):
        self.session.cookies.update({"oai-did": "did-123"})
        self.data["prod"] = "prod-123"
        self.data["device-id"] = "did-123"
        self.start_time = 0
        self.sid = "sid-123"
        self.data["config"] = [0] * 18

    monkeypatch.setattr(chatgpt_mod.ChatGPT, "_fetch_cookies", fake_fetch_cookies)

    def fake_get_tokens(self, process_time=0):
        self.data["proofofwork"] = {"seed": "seed", "difficulty": "abc"}
        self.data["bytecode"] = "bytecode"
        self.data["token"] = "req-token"
        self.data["vm_token"] = "vm-token"
        self.data["config"] = [0] * 18

    monkeypatch.setattr(chatgpt_mod.ChatGPT, "_get_tokens", fake_get_tokens)
    monkeypatch.setattr(chatgpt_mod.ChatGPT, "get_conduit", lambda self, next=False: "conduit-token")
    monkeypatch.setattr(chatgpt_mod.Challenges, "solve_pow", staticmethod(lambda seed, difficulty, config: "proof-token"))
    monkeypatch.setattr(chatgpt_mod.VM, "get_turnstile", staticmethod(lambda bytecode, token, ip_info: "turnstile-token"))


def test_ask_question_text_payload_includes_selected_thinking_mode(monkeypatch):
    _patch_chatgpt_bootstrap(monkeypatch)

    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return DummyResponse(
            'data: {"o":"append","p":"/message/content/parts/0","v":"hello there"}\n'
            '"conversation_id": "conv-123", "message_id": "msg-123"\n'
        )

    client = chatgpt_mod.ChatGPT(thinking_mode="extended", model_name="generic-model-id", transport_mode="anon")
    client.session.post = fake_post

    status = client.get_session_status()
    assert status["model_name"] == "generic-model-id"
    assert status["thinking_mode"] == "extended"
    assert status["transport_mode"] == "anon"
    assert status["bootstrap_ready"] is True
    assert status["login_state"] == "NOT_VERIFIED"

    response = client.ask_question("hello")

    assert response == "hello there"
    assert captured["url"] == "https://chatgpt.com/backend-anon/f/conversation"
    assert captured["timeout"] == (30, 300)
    assert captured["json"]["effort"] == "extended"
    assert captured["json"]["model"] == "generic-model-id"
    assert captured["json"]["messages"][0]["content"]["content_type"] == "text"
    assert captured["json"]["messages"][0]["content"]["parts"] == ["hello"]

    diagnostics = client.get_debug_summary()["request_diagnostics"]
    assert diagnostics["selected_transport_mode"] == "anon"
    assert diagnostics["effective_transport_mode"] == "anon"
    assert diagnostics["endpoint_family"] == "backend-anon"
    assert diagnostics["fallback_occurred"] is False


def test_ask_question_without_ids_still_returns_answer(monkeypatch):
    _patch_chatgpt_bootstrap(monkeypatch)

    def fake_post(url, json=None, timeout=None):
        return DummyResponse('data: {"o":"append","p":"/message/content/parts/0","v":"plain answer"}\n')

    client = chatgpt_mod.ChatGPT(thinking_mode="extended", model_name="generic-model-id", transport_mode="anon")
    client.session.post = fake_post

    response = client.ask_question("hello")
    assert response == "plain answer"


def test_ask_question_image_path_uses_multimodal_payload(monkeypatch):
    _patch_chatgpt_bootstrap(monkeypatch)

    captured = {}

    def fake_upload_file(self, file_name, file_b64, is_image=False, is_zip=False):
        captured["upload"] = {
            "file_name": file_name,
            "file_b64": file_b64,
            "is_image": is_image,
            "is_zip": is_zip,
        }
        return "file-123", 12, 1, 1

    def fake_post(url, json=None, timeout=None):
        captured["json"] = json
        captured["timeout"] = timeout
        return DummyResponse(
            'data: {"o":"append","p":"/message/content/parts/0","v":"ok"}\n'
            '"conversation_id": "conv-123", "message_id": "msg-123"\n'
        )

    monkeypatch.setattr(chatgpt_mod.ChatGPT, "upload_file", fake_upload_file)

    client = chatgpt_mod.ChatGPT(thinking_mode="pro", model_name="generic-model-id", transport_mode="anon")
    client.session.post = fake_post

    status = client.get_session_status()
    assert status["model_name"] == "generic-model-id"
    assert status["thinking_mode"] == "pro"
    assert status["login_state"] == "NOT_VERIFIED"

    response = client.ask_question("describe this", "data:image/png;base64,AAAA")

    assert response == "ok"
    assert captured["timeout"] == (30, 300)
    assert captured["upload"]["is_image"] is True
    assert captured["json"]["effort"] == "pro"
    assert captured["json"]["model"] == "generic-model-id"
    assert captured["json"]["messages"][0]["content"]["content_type"] == "multimodal_text"
    assert captured["json"]["messages"][0]["content"]["parts"][1] == "describe this"


def test_ask_question_raises_clear_error_when_response_is_empty(monkeypatch):
    _patch_chatgpt_bootstrap(monkeypatch)

    def fake_post(url, json=None, timeout=None):
        return DummyResponse("unexpected response")

    client = chatgpt_mod.ChatGPT(thinking_mode="extended", model_name="generic-model-id", transport_mode="anon")
    client.session.post = fake_post

    with pytest.raises(RuntimeError) as exc:
        client.ask_question("hello")

    assert "Conversation response did not contain a usable answer or conversation id" in str(exc.value)


def test_authenticated_mode_fails_loudly_without_required_session_material(monkeypatch):
    _patch_chatgpt_bootstrap(monkeypatch)

    client = chatgpt_mod.ChatGPT(transport_mode="authenticated")

    with pytest.raises(RuntimeError) as exc:
        client.ask_question("hello")

    message = str(exc.value)
    assert "Authenticated transport preflight failed" in message
    assert "authorization" in message

    diagnostics = client.get_debug_summary()["request_diagnostics"]
    assert diagnostics["selected_transport_mode"] == "authenticated"
    assert diagnostics["effective_transport_mode"] == "authenticated"
    assert diagnostics["endpoint_family"] == "authenticated-web"
    assert diagnostics["fallback_occurred"] is False
    assert diagnostics["history_verification"] == "not_checked"


def test_transport_audit_exposes_anon_endpoints_and_authenticated_slots(monkeypatch):
    _patch_chatgpt_bootstrap(monkeypatch)

    client = chatgpt_mod.ChatGPT(
        transport_mode="anon",
        endpoint_overrides={"conversation": "https://chatgpt.com/backend-api/conversation"},
        extra_headers={"x-test": "1"},
    )
    audit = client.get_transport_audit()

    assert audit["selected_transport_mode"] == "anon"
    assert audit["anon_endpoints"]["conversation"] == "https://chatgpt.com/backend-anon/f/conversation"
    assert audit["anon_header_inventory"]["conversation"][0] == "oai-client-version"
    assert "history_and_training_disabled" in audit["anon_payload_audit"]["history_suppressing_fields"]
    assert "prepare_conversation_conduit_token" in audit["anon_flow_stages"]
    assert "history_sync" in audit["authenticated_endpoint_slots"]
    assert audit["authenticated_endpoint_slots"]["conversation"] == "https://chatgpt.com/backend-api/f/conversation"
    assert audit["endpoint_overrides"]["conversation"] == "https://chatgpt.com/backend-api/conversation"
    assert audit["extra_headers"] == ["x-test"]


def test_authenticated_mode_sends_backend_api_payload_without_history_disabled(monkeypatch):
    _patch_chatgpt_bootstrap(monkeypatch)

    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return DummyResponse(
            'data: {"o":"append","p":"/message/content/parts/0","v":"auth answer"}\n'
            '"conversation_id":"conv-auth","message_id":"msg-auth"\n'
        )

    client = chatgpt_mod.ChatGPT(
        transport_mode="authenticated",
        cookies={"session": "token"},
        authorization="Bearer abc",
    )
    client.session.post = fake_post

    response = client.ask_question("hello")

    assert response == "auth answer"
    assert captured["url"] == "https://chatgpt.com/backend-api/f/conversation"
    assert captured["timeout"] == (30, 300)
    assert captured["json"]["action"] == "next"
    assert captured["json"]["parent_message_id"] == "client-created-root"
    assert captured["json"]["messages"][0]["content"]["parts"] == ["hello"]
    assert captured["json"]["thinking_effort"] == "instant"
    assert "effort" not in captured["json"]
    assert "history_and_training_disabled" not in captured["json"]
    assert client.data["conversation_id"] == "conv-auth"
    assert client.data["parent_message_id"] == "msg-auth"

    diagnostics = client.get_debug_summary()["request_diagnostics"]
    assert diagnostics["effective_transport_mode"] == "authenticated"
    assert diagnostics["endpoint_family"] == "authenticated-web"
    assert diagnostics["fallback_occurred"] is False
    assert diagnostics["remote_conversation_id"] == "conv-auth"
    assert client.get_debug_summary()["last_request_summary"]["history_and_training_disabled_sent"] is False


def test_centralized_header_builder_does_not_mutate_templates(monkeypatch):
    _patch_chatgpt_bootstrap(monkeypatch)

    original_conversation_authorization = chatgpt_mod.Headers.CONVERSATION.get("Authorization")
    client = chatgpt_mod.ChatGPT(transport_mode="anon", authorization="Bearer abc")

    headers = client._headers_for(
        "conversation",
        extra={"x-conduit-token": "conduit-token", "openai-sentinel-proof-token": "proof-token"},
        authenticated=False,
    )

    assert headers["Authorization"] == "Bearer abc"
    assert headers["oai-client-version"] == "prod-123"
    assert headers["oai-device-id"] == "did-123"
    assert headers["x-conduit-token"] == "conduit-token"
    assert headers["openai-sentinel-proof-token"] == "proof-token"
    assert chatgpt_mod.Headers.CONVERSATION.get("Authorization") == original_conversation_authorization
    assert chatgpt_mod.Headers.CONVERSATION["x-conduit-token"] == ""


def test_authenticated_mode_can_explicitly_fallback_to_anon(monkeypatch):
    _patch_chatgpt_bootstrap(monkeypatch)

    def fake_post(url, json=None, timeout=None):
        return DummyResponse(
            'data: {"o":"append","p":"/message/content/parts/0","v":"fallback answer"}\n'
            '"conversation_id": "conv-123", "message_id": "msg-123"\n'
        )

    client = chatgpt_mod.ChatGPT(transport_mode="authenticated", allow_anon_fallback=True)
    client.session.post = fake_post

    response = client.ask_question("hello")
    assert response == "fallback answer"

    diagnostics = client.get_debug_summary()["request_diagnostics"]
    assert diagnostics["selected_transport_mode"] == "authenticated"
    assert diagnostics["effective_transport_mode"] == "anon"
    assert diagnostics["endpoint_family"] == "backend-anon"
    assert diagnostics["fallback_occurred"] is True
