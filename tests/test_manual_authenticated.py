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

    def send_message(self, message, image=None, *, new_conversation=True):
        class Result:
            text = f"ok:{message}"
            transport_details = {"selected_transport_mode": self.transport_mode}
        return Result()


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
    monkeypatch.setattr(auth_manual, "extract_websocket_url_from_har", lambda path: "wss://ws.chatgpt.com/test")
    monkeypatch.setattr(auth_manual, "load_json", lambda path="session.json": {} if path != "session.json" else {})

    captured = {}

    def fake_build_transport(session_material):
        captured.update(session_material)
        return DummyChatGPT(
            cookies=session_material.get("cookies"),
            authorization=session_material.get("authorization"),
            thinking_mode=session_material.get("thinking_mode", "instant"),
            model_name=session_material.get("model_name", "auto"),
            transport_mode=session_material.get("transport_mode", "authenticated"),
            allow_anon_fallback=session_material.get("allow_anon_fallback", False),
            websocket_url=session_material.get("websocket_url"),
            websocket_verify_token=session_material.get("websocket_verify_token"),
        )

    monkeypatch.setattr(auth_manual, "build_transport", fake_build_transport)

    client = auth_manual.build_authenticated_client(
        {"thinking_mode": "extended", "model_name": "auto", "allow_anon_fallback": False},
        {"oai-did": "did-123"},
    )

    assert isinstance(client, DummyChatGPT)
    assert client.transport_mode == "authenticated"
    assert client.cookies == {"oai-did": "did-123"}
    assert client.websocket_url == "wss://ws.chatgpt.com/test"
    assert captured["transport_mode"] == "authenticated"


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
    discovery_file = tmp_path / "session.discovered.json"
    discovery_file.write_text(json.dumps({
        "websocket_url": "wss://ws.chatgpt.com/from-discovery",
        "resume_conversation_token": "resume-token",
    }), encoding="utf-8")

    monkeypatch.setattr(
        auth_manual,
        "build_transport",
        lambda session_material: DummyChatGPT(
            cookies=session_material.get("cookies"),
            websocket_url=session_material.get("websocket_url"),
            websocket_verify_token=session_material.get("websocket_verify_token"),
        ),
    )

    client = auth_manual.build_authenticated_client(
        {"websocket_discovery_path": str(discovery_file)},
        {"oai-did": "did-123"},
    )

    assert client.websocket_url == "wss://ws.chatgpt.com/from-discovery"
    assert client.websocket_verify_token == "resume-token"


def test_build_authenticated_client_supports_playwright_transport(monkeypatch):
    captured = {}

    def fake_build_transport(session_material):
        captured.update(session_material)
        return DummyChatGPT(transport_mode=session_material.get("transport_mode", "authenticated"))

    monkeypatch.setattr(auth_manual, "build_transport", fake_build_transport)

    client = auth_manual.build_authenticated_client(
        {
            "transport_mode": "playwright",
            "browser_user_data_dir": "/tmp/chromium",
            "browser_profile_directory": "Default",
            "browser_executable_path": "/usr/bin/chromium",
            "browser_connect_over_cdp": True,
            "browser_cdp_url": "http://127.0.0.1:9222",
            "browser_auto_start_debug_browser": True,
            "browser_debugging_port": 9222,
        },
        {},
    )

    assert client.transport_mode == "playwright"
    assert captured["browser_user_data_dir"] == "/tmp/chromium"
    assert captured["browser_profile_directory"] == "Default"
    assert captured["browser_connect_over_cdp"] is True
    assert captured["browser_cdp_url"] == "http://127.0.0.1:9222"
    assert captured["browser_auto_start_debug_browser"] is True
    assert captured["browser_debugging_port"] == 9222


def test_merge_browser_settings_fills_missing_session_fields(tmp_path):
    browser_settings = tmp_path / "browser-settings.json"
    browser_settings.write_text(json.dumps({
        "browser_user_data_dir": "/tmp/chromium",
        "browser_profile_directory": "Default",
        "browser_connect_over_cdp": True,
    }), encoding="utf-8")

    merged = auth_manual.merge_browser_settings(
        {"transport_mode": "playwright", "browser_profile_directory": ""},
        str(browser_settings),
    )

    assert merged["browser_user_data_dir"] == "/tmp/chromium"
    assert merged["browser_profile_directory"] == "Default"
    assert merged["browser_connect_over_cdp"] is True


def test_load_discovered_cookies_reads_cookie_map(tmp_path):
    discovery_file = tmp_path / "session.discovered.json"
    discovery_file.write_text(json.dumps({"cookies": {"oai-did": "did-123", "cf_clearance": "cf"}}), encoding="utf-8")

    assert auth_manual.load_discovered_cookies(str(discovery_file)) == {"oai-did": "did-123", "cf_clearance": "cf"}


def test_load_json_returns_empty_when_missing(tmp_path):
    assert auth_manual.load_json(str(tmp_path / "missing.json")) == {}

    fixture = tmp_path / "session.json"
    fixture.write_text(json.dumps({"message": "hello"}), encoding="utf-8")
    assert auth_manual.load_json(str(fixture))["message"] == "hello"
