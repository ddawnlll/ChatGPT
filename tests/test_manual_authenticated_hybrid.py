import json

import manual_authenticated_hybrid as hybrid


class DummyClient:
    def __init__(self):
        self.websocket_url = "wss://ws.chatgpt.com/test"

    def get_session_status(self):
        return {"transport_mode": "authenticated"}

    def get_transport_audit(self):
        return {"selected_transport_mode": "authenticated"}

    def get_debug_summary(self):
        return {"request_diagnostics": {"selected_transport_mode": "authenticated"}}

    def send_message(self, message, image=None, *, new_conversation=True):
        class Result:
            text = f"ok:{message}"
            transport_details = {"selected_transport_mode": "authenticated"}
        return Result()


def test_refresh_hybrid_session_material_runs_extractor(monkeypatch, tmp_path, capsys):
    discovery_file = tmp_path / "session.discovered.json"
    discovery_file.write_text(json.dumps({"cookies": {"oai-did": "did-123"}, "websocket_url": "wss://ws.chatgpt.com/test"}), encoding="utf-8")

    commands = []

    class DummyCompleted:
        returncode = 0

    monkeypatch.setattr(hybrid, "run", lambda command, check=False: commands.append(command) or DummyCompleted())
    result = hybrid.refresh_hybrid_session_material(
        {
            "websocket_discovery_path": str(discovery_file),
            "browser_chat_url": "https://chatgpt.com/",
            "browser_executable_path": "/usr/bin/chromium",
            "browser_user_data_dir": "/tmp/chromium",
            "browser_profile_directory": "Default",
            "browser_cdp_url": "http://127.0.0.1:9222",
            "browser_debugging_port": 9222,
            "browser_auto_start_debug_browser": True,
            "browser_connect_over_cdp": True,
        }
    )

    assert commands
    assert result["websocket_url"] == "wss://ws.chatgpt.com/test"


def test_hybrid_main_forces_authenticated_transport(monkeypatch, tmp_path, capsys):
    session_file = tmp_path / "session.json"
    session_file.write_text(json.dumps({
        "transport_mode": "playwright",
        "message": "hello",
        "browser_settings_path": str(tmp_path / "browser-settings.json"),
    }), encoding="utf-8")
    (tmp_path / "browser-settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "session.discovered.json").write_text(json.dumps({
        "cookies": {"oai-did": "did-123", "__Secure-next-auth.session-token.0": "token-0"},
        "websocket_url": "wss://ws.chatgpt.com/test",
    }), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    captured = {}

    def fake_build_authenticated_client(session_data, cookies):
        captured.update(session_data)
        assert cookies["oai-did"] == "did-123"
        return DummyClient()

    monkeypatch.setattr(hybrid, "refresh_hybrid_session_material", lambda session_data: hybrid.shared.load_json(str(tmp_path / "session.discovered.json")))
    monkeypatch.setattr(hybrid.shared, "build_authenticated_client", fake_build_authenticated_client)
    monkeypatch.setattr(hybrid.shared, "attach_http_tracing", lambda *args, **kwargs: None)
    monkeypatch.setattr(hybrid.shared, "attach_stage_tracing", lambda *args, **kwargs: None)

    hybrid.main()
    output = capsys.readouterr().out

    assert captured["transport_mode"] == "authenticated"
    assert captured["websocket_url"] == "wss://ws.chatgpt.com/test"
    assert "[auth-hybrid] transport_mode=authenticated" in output
    assert "[auth-hybrid] response_start" in output
