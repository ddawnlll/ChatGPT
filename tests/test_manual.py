import json

import pytest

import manual


class DummyChatGPT:
    def __init__(self, proxy=None, cookies=None, authorization=None, thinking_mode="instant", model_name="auto"):
        self.proxy = proxy
        self.cookies = cookies
        self.authorization = authorization
        self.thinking_mode = thinking_mode
        self.model_name = model_name

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
            "cookies": {"session": "token"},
            "authorization": "Bearer abc",
            "thinking_mode": "pro",
            "model_name": "generic-model-id",
        }
    )

    assert isinstance(client, DummyChatGPT)
    assert client.proxy is None
    assert client.cookies == {"session": "token"}
    assert client.authorization == "Bearer abc"
    assert client.thinking_mode == "pro"
    assert client.model_name == "generic-model-id"


def test_get_session_preflight_detects_identity_cookie():
    info = manual.get_session_preflight(
        {
            "cookies": [
                {"name": "__Secure-next-auth.session-token.0", "value": "token"},
                {"name": "oai-did", "value": "did-123"},
            ],
            "authorization": "Bearer abc",
            "thinking_mode": "extended",
            "model_name": "generic-model-id",
        }
    )

    assert info["has_cookies"] is True
    assert info["cookie_count"] == 2
    assert info["has_identity_cookie"] is True
    assert info["has_authorization"] is True
    assert info["authorization_present"] is True
    assert info["authorization_type"] == "str"
    assert info["authorization_non_empty"] is True
    assert info["authorization_prefix_bearer"] is True
    assert info["authorization_length"] == len("Bearer abc")
    assert info["has_model_name"] is True
    assert info["model_name"] == "generic-model-id"
    assert info["thinking_mode"] == "extended"


def test_print_session_preflight(capsys):
    manual.print_session_preflight(
        {
            "cookies": {"session": "token"},
            "authorization": "Bearer abc",
            "thinking_mode": "extended",
            "model_name": "generic-model-id",
        }
    )
    output = capsys.readouterr().out
    assert "PRECHECK: SESSION FILE OK | LOGIN STATUS UNVERIFIED" in output
    assert "has_cookies=True" in output
    assert "has_identity_cookie=False" in output
    assert "authorization_present=True" in output
    assert "authorization_type=str" in output
    assert "authorization_non_empty=True" in output
    assert "authorization_prefix_bearer=True" in output
    assert "model_name=generic-model-id" in output
    assert "thinking_mode=extended" in output


def test_print_session_status(capsys):
    client = DummyChatGPT(
        cookies={"session": "token"},
        authorization="Bearer abc",
        thinking_mode="extended",
        model_name="generic-model-id",
    )
    client.session_status = {
        "bootstrap_ready": True,
        "proxy_supplied": False,
        "cookies_supplied": True,
        "authorization_supplied": True,
        "model_name": "generic-model-id",
        "thinking_mode": "extended",
        "device_id_present": True,
        "session_material_loaded": True,
        "login_state": "LIKELY_AUTHENTICATED",
        "login_reasons": [],
    }

    manual.print_session_status(client)
    output = capsys.readouterr().out
    assert "SESSION MATERIAL LOADED | LOGIN LIKELY VERIFIED" in output
    assert "ready=True" in output
    assert "cookies_supplied=True" in output
    assert "authorization_supplied=True" in output
    assert "model_name=generic-model-id" in output
    assert "thinking_mode=extended" in output


def test_print_debug_dump(capsys):
    client = DummyChatGPT(
        cookies={"session": "token"},
        authorization=None,
        thinking_mode="extended",
        model_name="generic-model-id",
    )
    client.session_status = {
        "login_state": "NOT_VERIFIED",
        "device_id_present": True,
        "login_reasons": ["authorization not supplied"],
    }

    manual.print_debug_dump(
        {
            "cookies": {"session": "token"},
            "thinking_mode": "extended",
            "model_name": "generic-model-id",
        },
        client,
        "blocked",
        request_sent=False,
    )
    output = capsys.readouterr().out
    assert "blocked_reason=blocked" in output
    assert "required_for_strict_login=authorization_supplied=True" in output
    assert "authorization_present=False" in output
    assert "authorization_type=missing" in output
    assert "authorization_non_empty=False" in output
    assert "authorization_prefix_bearer=False" in output
    assert "request_sent=False" in output


def test_enforce_login_requirement_blocks_unverified_login():
    client = DummyChatGPT(
        cookies={"session": "token"},
        authorization=None,
        thinking_mode="extended",
        model_name="generic-model-id",
    )
    client.session_status = {
        "bootstrap_ready": True,
        "proxy_supplied": False,
        "cookies_supplied": True,
        "authorization_supplied": False,
        "model_name": "generic-model-id",
        "thinking_mode": "extended",
        "device_id_present": False,
        "session_material_loaded": True,
        "login_state": "NOT_VERIFIED",
        "login_reasons": ["oai-did cookie missing after bootstrap"],
    }

    with pytest.raises(RuntimeError) as exc:
        manual.enforce_login_requirement(
            {
                "require_login": True,
                "cookies": {"session": "token"},
                "thinking_mode": "extended",
                "model_name": "generic-model-id",
            },
            client,
        )

    assert "LOGIN REQUIRED: blocked request because login could not be verified" in str(exc.value)
    assert "authorization is required when require_login=true; cookie presence alone is not sufficient" in str(exc.value)
    assert "oai-did cookie was not present after bootstrap" in str(exc.value)
