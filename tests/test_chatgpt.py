import wrapper.chatgpt as chatgpt_mod


class DummyResponse:
    def __init__(self, text: str, cookies=None):
        self.text = text
        self.cookies = cookies or {}


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

    client = chatgpt_mod.ChatGPT(thinking_mode="extended", model_name="generic-model-id")
    client.session.post = fake_post

    status = client.get_session_status()
    assert status["model_name"] == "generic-model-id"
    assert status["thinking_mode"] == "extended"
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

    client = chatgpt_mod.ChatGPT(thinking_mode="pro", model_name="generic-model-id")
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
