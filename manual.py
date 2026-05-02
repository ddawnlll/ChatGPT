from json import load
from pathlib import Path

from wrapper import ChatGPT

IDENTITY_COOKIE_NAMES = {
    "oai-did",
    "__Secure-oai-is",
}
IDENTITY_COOKIE_PREFIXES = (
    "__Secure-next-auth.session-token",
)


def load_session_fixture(path: str = "session.json") -> dict:
    fixture_path = Path(path)
    if not fixture_path.exists():
        return {}

    with fixture_path.open("r", encoding="utf-8") as handle:
        return load(handle)


def build_client_from_fixture(session_data: dict) -> ChatGPT:
    return ChatGPT(
        cookies=session_data.get("cookies"),
        authorization=session_data.get("authorization"),
        thinking_mode=session_data.get("thinking_mode", "extended"),
        model_name=session_data.get("model_name", "auto"),
    )


def _extract_cookie_names(session_data: dict) -> list[str]:
    cookies = session_data.get("cookies")
    if isinstance(cookies, dict):
        return list(cookies.keys())
    if isinstance(cookies, list):
        names: list[str] = []
        for cookie in cookies:
            if isinstance(cookie, dict) and cookie.get("name"):
                names.append(str(cookie["name"]))
        return names
    if isinstance(cookies, str):
        names: list[str] = []
        for cookie_part in cookies.split(";"):
            if "=" not in cookie_part:
                continue
            name, _ = cookie_part.split("=", 1)
            name = name.strip()
            if name:
                names.append(name)
        return names
    return []


def get_session_preflight(session_data: dict) -> dict:
    cookie_names = _extract_cookie_names(session_data)
    has_identity_cookie = any(
        name in IDENTITY_COOKIE_NAMES or any(name.startswith(prefix) for prefix in IDENTITY_COOKIE_PREFIXES)
        for name in cookie_names
    )
    raw_authorization = session_data.get("authorization")
    authorization_present = "authorization" in session_data
    authorization_type = type(raw_authorization).__name__ if authorization_present else "missing"
    authorization_non_empty = isinstance(raw_authorization, str) and bool(raw_authorization.strip())
    authorization_prefix_bearer = authorization_non_empty and raw_authorization.strip().startswith("Bearer ")
    authorization_length = len(raw_authorization.strip()) if authorization_non_empty else 0
    return {
        "keys": sorted(session_data.keys()),
        "has_cookies": bool(session_data.get("cookies")),
        "cookie_count": len(cookie_names),
        "has_identity_cookie": has_identity_cookie,
        "has_authorization": bool(session_data.get("authorization")),
        "authorization_present": authorization_present,
        "authorization_type": authorization_type,
        "authorization_non_empty": authorization_non_empty,
        "authorization_prefix_bearer": authorization_prefix_bearer,
        "authorization_length": authorization_length,
        "has_model_name": bool(session_data.get("model_name")),
        "model_name": session_data.get("model_name", "auto"),
        "thinking_mode": session_data.get("thinking_mode", "extended"),
    }


def print_session_preflight(session_data: dict) -> None:
    info = get_session_preflight(session_data)
    if info["has_identity_cookie"]:
        state = "PRECHECK: IDENTITY COOKIE PRESENT | LOGIN STATUS UNVERIFIED"
    elif info["has_cookies"] or info["has_authorization"]:
        state = "PRECHECK: SESSION FILE OK | LOGIN STATUS UNVERIFIED"
    else:
        state = "PRECHECK: NO SESSION MATERIAL | LOGIN STATUS UNVERIFIED"

    print(
        f"[preflight] {state}\n"
        f"[preflight] keys={', '.join(info['keys']) or '-'}\n"
        f"[preflight] has_cookies={info['has_cookies']} cookie_count={info['cookie_count']} "
        f"has_identity_cookie={info['has_identity_cookie']} has_authorization={info['has_authorization']} "
        f"authorization_present={info['authorization_present']} authorization_type={info['authorization_type']} authorization_non_empty={info['authorization_non_empty']} "
        f"authorization_prefix_bearer={info['authorization_prefix_bearer']} authorization_length={info['authorization_length']} "
        f"has_model_name={info['has_model_name']} model_name={info['model_name']} "
        f"thinking_mode={info['thinking_mode']}"
    )


def print_session_status(client: ChatGPT) -> None:
    status = client.get_session_status() if hasattr(client, "get_session_status") else getattr(client, "session_status", {})
    login_state = status.get("login_state", "NOT_VERIFIED")
    if login_state == "LIKELY_AUTHENTICATED":
        human_state = "SESSION MATERIAL LOADED | LOGIN LIKELY VERIFIED"
    elif status.get("session_material_loaded", False):
        human_state = "SESSION MATERIAL LOADED | LOGIN NOT VERIFIED"
    else:
        human_state = "NO SESSION MATERIAL | LOGIN NOT VERIFIED"

    print(
        f"[session] {human_state}\n"
        f"[session] ready={status.get('bootstrap_ready', False)} "
        f"proxy_supplied={status.get('proxy_supplied', False)} "
        f"cookies_supplied={status.get('cookies_supplied', False)} "
        f"authorization_supplied={status.get('authorization_supplied', False)} "
        f"model_name={status.get('model_name')} "
        f"thinking_mode={status.get('thinking_mode')} "
        f"device_id_present={status.get('device_id_present', False)}"
    )


def print_debug_dump(session_data: dict, client: ChatGPT, reason: str, request_sent: bool = False) -> None:
    preflight = get_session_preflight(session_data)
    debug_summary = client.get_debug_summary() if hasattr(client, "get_debug_summary") else {
        "session_status": getattr(client, "session_status", {}),
        "last_request_summary": {},
        "last_response_summary": {},
    }
    session_status = debug_summary.get("session_status", {})
    last_request = debug_summary.get("last_request_summary", {})
    last_response = debug_summary.get("last_response_summary", {})

    print(f"[debug] blocked_reason={reason}")
    print(
        "[debug] required_for_strict_login="
        "authorization_supplied=True, "
        "device_id_present=True, "
        "bootstrap_ready=True"
    )
    print(
        f"[debug] given has_cookies={preflight.get('has_cookies')} "
        f"has_identity_cookie={preflight.get('has_identity_cookie')} "
        f"has_authorization={preflight.get('has_authorization')} "
        f"authorization_present={preflight.get('authorization_present')} "
        f"authorization_type={preflight.get('authorization_type')} "
        f"authorization_non_empty={preflight.get('authorization_non_empty')} "
        f"authorization_prefix_bearer={preflight.get('authorization_prefix_bearer')} "
        f"authorization_length={preflight.get('authorization_length')} "
        f"model_name={preflight.get('model_name')} "
        f"thinking_mode={preflight.get('thinking_mode')}"
    )
    print(
        f"[debug] runtime login_state={session_status.get('login_state')} "
        f"device_id_present={session_status.get('device_id_present')} "
        f"login_reasons={session_status.get('login_reasons', [])}"
    )
    print(f"[debug] request_sent={request_sent or last_request.get('request_sent', False)}")
    if last_request:
        print(
            f"[debug] request_summary url={last_request.get('url')} model={last_request.get('model')} "
            f"thinking_mode={last_request.get('thinking_mode')} has_image={last_request.get('has_image')} "
            f"message_length={last_request.get('message_length')}"
        )
    if last_response:
        print(
            f"[debug] response_summary received={last_response.get('response_received')} "
            f"status_code={last_response.get('status_code')} unusual_activity={last_response.get('unusual_activity')} "
            f"conversation_id_found={last_response.get('conversation_id_found')}"
        )
        if last_response.get('text_preview'):
            print(f"[debug] response_preview={last_response.get('text_preview')}")


def enforce_login_requirement(session_data: dict, client: ChatGPT) -> None:
    if not session_data.get("require_login", False):
        return

    preflight = get_session_preflight(session_data)
    status = client.get_session_status() if hasattr(client, "get_session_status") else getattr(client, "session_status", {})
    reasons: list[str] = []

    if not preflight.get("has_cookies") and not preflight.get("has_authorization"):
        reasons.append("no session material was provided")
    if not preflight.get("has_authorization"):
        reasons.append("authorization is required when require_login=true; cookie presence alone is not sufficient")
    if not preflight.get("has_identity_cookie") and not preflight.get("has_authorization"):
        reasons.append("no recognizable identity cookie or authorization was found in session.json")
    if not status.get("device_id_present", False):
        reasons.append("oai-did cookie was not present after bootstrap")
    for reason in status.get("login_reasons", []):
        if reason not in reasons:
            reasons.append(reason)

    if status.get("login_state") != "LIKELY_AUTHENTICATED":
        reason_text = "; ".join(reasons) if reasons else "login state could not be verified"
        raise RuntimeError(f"LOGIN REQUIRED: blocked request because login could not be verified: {reason_text}")


def main() -> None:
    session_data = load_session_fixture()
    if not session_data:
        print(ChatGPT().ask_question("Test"))
        return

    print_session_preflight(session_data)
    client = build_client_from_fixture(session_data)
    print_session_status(client)

    try:
        enforce_login_requirement(session_data, client)
    except RuntimeError as exc:
        print(f"[session] {exc}")
        print_debug_dump(session_data, client, str(exc), request_sent=False)
        return

    message = session_data.get("message", "Test")
    try:
        print(client.ask_question(message))
    except Exception as exc:
        print(f"[session] request failed: {exc}")
        print_debug_dump(session_data, client, str(exc), request_sent=True)
        raise


if __name__ == "__main__":
    main()
