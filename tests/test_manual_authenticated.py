import json

import manual_authenticated as auth_manual


class DummyChatGPT:
    def __init__(self, cookies=None, authorization=None, thinking_mode="instant", model_name="auto", transport_mode="authenticated", allow_anon_fallback=False, websocket_url=None, websocket_verify_token=None):
        self.cookies = cookies
        self.authorization = authorization
        self.thinking_mode = thinking_mode
        self.model_name = model_name
        self.transport_mode = transport_mode
        self.allow_anon_fallback = allow_anon_fallback
        self.websocket_url = websocket_url
        self.websocket_verify_token = websocket_verify_token

    def get_session_status(self):
        return {"transport_mode": self.transport_mode, "cookies_supplied": bool(self.cookies)}

    def get_transport_audit(self):
        return {"selected_transport_mode": self.transport_mode}

    def get_debug_summary(self):
        return {"request_diagnostics": {"selected_transport_mode": self.transport_mode}}

    def ask_question(self, message):
        return f"ok:{message}"


def test_parse_netscape_cookies_txt_filters_chatgpt_and_openai_domains(tmp_path):
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(
        "# Netscape HTTP Cookie File\n"
        ".chatgpt.com\tTRUE\t/\tTRUE\t0\toai-did\tdid-123\n"
        ".openai.com\tTRUE\t/\tTRUE\t0\toai-sc\tsc-123\n"
        ".google.com\tTRUE\t/\tTRUE\t0\tSID\tignore\n",
        encoding="utf-8",
    )

    cookies = auth_manual.parse_netscape_cookies_txt(str(cookie_file))
    assert cookies == {"oai-did": "did-123", "oai-sc": "sc-123"}


def test_select_authenticated_cookies_keeps_identity_and_session_cookies():
    selected = auth_manual.select_authenticated_cookies(
        {
            "oai-did": "did-123",
            "__Secure-next-auth.session-token.0": "token-0",
            "__Secure-oai-is": "ois",
            "SID": "ignore",
        }
    )

    assert selected == {
        "oai-did": "did-123",
        "__Secure-next-auth.session-token.0": "token-0",
        "__Secure-oai-is": "ois",
    }


def test_build_authenticated_client_uses_authenticated_transport(monkeypatch):
    monkeypatch.setattr(auth_manual, "ChatGPT", DummyChatGPT)
    monkeypatch.setattr(auth_manual, "extract_websocket_url_from_har", lambda path: "wss://ws.chatgpt.com/test")

    client = auth_manual.build_authenticated_client(
        {"thinking_mode": "extended", "model_name": "auto", "allow_anon_fallback": False},
        {"oai-did": "did-123"},
    )

    assert isinstance(client, DummyChatGPT)
    assert client.transport_mode == "authenticated"
    assert client.cookies == {"oai-did": "did-123"}
    assert client.websocket_url == "wss://ws.chatgpt.com/test"


def test_extract_websocket_url_from_har_returns_latest_socket(tmp_path):
    har_file = tmp_path / "capture.har"
    har_file.write_text(json.dumps({
        "log": {
            "entries": [
                {"_resourceType": "websocket", "request": {"url": "wss://ws.chatgpt.com/one"}},
                {"_resourceType": "fetch", "request": {"url": "https://chatgpt.com/backend-api/f/conversation"}},
                {"_resourceType": "websocket", "request": {"url": "wss://ws.chatgpt.com/two"}},
            ]
        }
    }), encoding="utf-8")

    assert auth_manual.extract_websocket_url_from_har(str(har_file)) == "wss://ws.chatgpt.com/two"


def test_build_authenticated_client_uses_discovery_file_when_session_lacks_websocket(monkeypatch, tmp_path):
    monkeypatch.setattr(auth_manual, "ChatGPT", DummyChatGPT)

    discovery_file = tmp_path / "session.discovered.json"
    discovery_file.write_text(json.dumps({
        "websocket_url": "wss://ws.chatgpt.com/from-discovery",
        "resume_conversation_token": "resume-token",
    }), encoding="utf-8")

    client = auth_manual.build_authenticated_client(
        {"websocket_discovery_path": str(discovery_file)},
        {"oai-did": "did-123"},
    )

    assert client.websocket_url == "wss://ws.chatgpt.com/from-discovery"
    assert client.websocket_verify_token == "resume-token"


def test_load_json_returns_empty_when_missing(tmp_path):
    assert auth_manual.load_json(str(tmp_path / "missing.json")) == {}

    fixture = tmp_path / "session.json"
    fixture.write_text(json.dumps({"message": "hello"}), encoding="utf-8")
    assert auth_manual.load_json(str(fixture))["message"] == "hello"
