import pytest

import api_server


@pytest.fixture(autouse=True)
def clear_session_store():
    api_server.SESSION_STORE.clear()
    yield
    api_server.SESSION_STORE.clear()


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
    )

    resolved_1 = api_server.resolve_session_material(request_1)
    assert resolved_1["session_id"] == "session-1"
    assert resolved_1["cookies"] == {"session": "token"}
    assert resolved_1["authorization"] == "Bearer abc"
    assert resolved_1["thinking_mode"] == "extended"

    request_2 = api_server.ConversationRequest(
        message="hello again",
        session_id="session-1",
    )

    resolved_2 = api_server.resolve_session_material(request_2)
    assert resolved_2["cookies"] == {"session": "token"}
    assert resolved_2["authorization"] == "Bearer abc"
    assert resolved_2["thinking_mode"] == "extended"


def test_resolve_session_material_rejects_invalid_thinking_mode():
    request = api_server.ConversationRequest(
        message="hello",
        thinking_mode="unsupported",
    )

    with pytest.raises(api_server.HTTPException):
        api_server.resolve_session_material(request)
