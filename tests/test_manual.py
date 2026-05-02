import json

import manual


class DummyChatGPT:
    def __init__(self, proxy=None, cookies=None, authorization=None, thinking_mode="instant"):
        self.proxy = proxy
        self.cookies = cookies
        self.authorization = authorization
        self.thinking_mode = thinking_mode

    def ask_question(self, message, image=None):
        return {
            "message": message,
            "image": image,
            "proxy": self.proxy,
            "cookies": self.cookies,
            "authorization": self.authorization,
            "thinking_mode": self.thinking_mode,
        }


def test_load_session_fixture(tmp_path):
    fixture_path = tmp_path / "session.json"
    fixture_path.write_text(json.dumps({"proxy": "127.0.0.1:8080", "message": "hello"}), encoding="utf-8")

    loaded = manual.load_session_fixture(str(fixture_path))
    assert loaded["proxy"] == "127.0.0.1:8080"
    assert loaded["message"] == "hello"


def test_build_client_from_fixture_uses_session_fields(monkeypatch):
    monkeypatch.setattr(manual, "ChatGPT", DummyChatGPT)

    client = manual.build_client_from_fixture(
        {
            "proxy": "127.0.0.1:8080",
            "cookies": {"session": "token"},
            "authorization": "Bearer abc",
            "thinking_mode": "pro",
        }
    )

    assert isinstance(client, DummyChatGPT)
    assert client.proxy is None
    assert client.cookies == {"session": "token"}
    assert client.authorization == "Bearer abc"
    assert client.thinking_mode == "pro"
