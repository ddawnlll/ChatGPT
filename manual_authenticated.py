from json import load
from pathlib import Path
from time import perf_counter
from typing import Any

from transport_runtime import ChatTransport, build_transport
from wrapper import ChatGPT

IDENTITY_COOKIE_PREFIXES = (
    "__Secure-next-auth.session-token",
)
IDENTITY_COOKIE_NAMES = {
    "oai-did",
    "__Secure-oai-is",
    "oai-sc",
    "_account",
    "_puid",
    "cf_clearance",
}


def load_json(path: str = "session.json") -> dict:
    session_path = Path(path)
    if not session_path.exists():
        return {}
    with session_path.open("r", encoding="utf-8") as handle:
        return load(handle)


def merge_browser_settings(session_data: dict, browser_settings_path: str = "browser-settings.json") -> dict:
    merged = dict(session_data)
    browser_settings = load_json(browser_settings_path)
    if not isinstance(browser_settings, dict):
        return merged
    for key, value in browser_settings.items():
        if key not in merged or merged.get(key) in (None, "", False):
            merged[key] = value
    return merged


def parse_netscape_cookies_txt(path: str = "cookies.txt") -> dict[str, str]:
    cookie_path = Path(path)
    if not cookie_path.exists():
        return {}

    cookies: dict[str, str] = {}
    with cookie_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 7:
                continue
            domain = parts[0]
            name = parts[5]
            value = "\t".join(parts[6:])
            if "chatgpt.com" not in domain and "openai.com" not in domain:
                continue
            cookies[name] = value
    return cookies


def select_authenticated_cookies(cookies: dict[str, str]) -> dict[str, str]:
    selected: dict[str, str] = {}
    for name, value in cookies.items():
        if name in IDENTITY_COOKIE_NAMES or any(name.startswith(prefix) for prefix in IDENTITY_COOKIE_PREFIXES):
            selected[name] = value
    return selected


def summarize_cookies(cookies: dict[str, str]) -> dict:
    names = sorted(cookies.keys())
    return {
        "count": len(names),
        "names": names,
        "has_session_token": any(name.startswith("__Secure-next-auth.session-token") for name in names),
        "has_oai_did": "oai-did" in cookies,
        "has_oai_is": "__Secure-oai-is" in cookies,
        "has_oai_sc": "oai-sc" in cookies,
        "has_cf_clearance": "cf_clearance" in cookies,
    }


def extract_websocket_url_from_har(path: str) -> str | None:
    har_path = Path(path)
    if not har_path.exists() or har_path.stat().st_size == 0:
        return None
    try:
        raw_text = har_path.read_text(encoding="utf-8")
    except Exception:
        raw_text = ""
    marker = "wss://ws.chatgpt.com/"
    if raw_text and marker in raw_text:
        start = raw_text.rfind(marker)
        end = raw_text.find('"', start)
        if end == -1:
            end = len(raw_text)
        return raw_text[start:end].replace('\\/', '/')
    try:
        payload = load_json(str(har_path))
    except Exception:
        return None
    entries = payload.get("log", {}).get("entries", [])
    websocket_urls = []
    for entry in entries:
        if entry.get("_resourceType") == "websocket" or "_webSocketMessages" in entry:
            url = ((entry.get("request") or {}).get("url"))
            if isinstance(url, str) and url.startswith("wss://ws.chatgpt.com/"):
                websocket_urls.append(url)
    return websocket_urls[-1] if websocket_urls else None


def build_authenticated_client(session_data: dict, cookies: dict[str, str]) -> ChatTransport:
    transport_mode = (session_data.get("transport_mode") or "authenticated").strip().lower()
    if transport_mode == "playwright":
        return build_transport(
            {
                "transport_mode": "playwright",
                "browser_user_data_dir": session_data.get("browser_user_data_dir") or session_data.get("user_data_dir"),
                "browser_profile_directory": session_data.get("browser_profile_directory") or session_data.get("profile_directory"),
                "browser_executable_path": session_data.get("browser_executable_path") or session_data.get("executable_path"),
                "browser_channel": session_data.get("browser_channel"),
                "browser_headless": bool(session_data.get("browser_headless", False)),
                "browser_chat_url": session_data.get("browser_chat_url"),
                "browser_capture_timeout_ms": session_data.get("browser_capture_timeout_ms"),
                "browser_connect_over_cdp": bool(session_data.get("browser_connect_over_cdp", False)),
                "browser_cdp_url": session_data.get("browser_cdp_url"),
                "browser_auto_start_debug_browser": bool(session_data.get("browser_auto_start_debug_browser", False)),
                "browser_debugging_port": session_data.get("browser_debugging_port"),
                "thinking_mode": session_data.get("thinking_mode", "extended"),
                "model_name": session_data.get("model_name", "auto"),
            }
        )

    authorization = session_data.get("authorization")
    websocket_url = session_data.get("websocket_url")
    websocket_verify_token = session_data.get("websocket_verify_token")
    if not websocket_url:
        discovery_path = session_data.get("websocket_discovery_path", "session.discovered.json")
        discovered = load_json(discovery_path)
        websocket_url = discovered.get("websocket_url") or websocket_url
        websocket_verify_token = discovered.get("resume_conversation_token") or websocket_verify_token
    if not websocket_url:
        har_path = session_data.get("websocket_har_path", "chatgpt.com3.har")
        websocket_url = extract_websocket_url_from_har(har_path)
        if not websocket_url:
            print(
                f"[auth-manual] websocket_url_missing_from_har path={har_path} "
                "(HAR exports often omit websocket frames/URLs; run bun run discover:ws or set session.json:websocket_url manually)"
            )
    return build_transport(
        {
            "cookies": cookies,
            "authorization": authorization,
            "thinking_mode": session_data.get("thinking_mode", "extended"),
            "model_name": session_data.get("model_name", "auto"),
            "transport_mode": "authenticated",
            "allow_anon_fallback": bool(session_data.get("allow_anon_fallback", False)),
            "websocket_url": websocket_url,
            "websocket_verify_token": websocket_verify_token,
        }
    )


def attach_http_tracing(client: ChatTransport, conversation_timeout_seconds: int | None = None) -> None:
    if not hasattr(client, "session") or not getattr(client, "session", None) or not hasattr(client.session, "post"):
        return
    original_post = client.session.post

    def traced_post(url: str, *args: Any, **kwargs: Any):
        start = perf_counter()
        if conversation_timeout_seconds and url.endswith('/backend-api/f/conversation'):
            kwargs['timeout'] = (30, conversation_timeout_seconds)
        print(f"[auth-manual] http_post_start url={url} stream={kwargs.get('stream', False)} timeout={kwargs.get('timeout')}")
        try:
            response = original_post(url, *args, **kwargs)
            elapsed = perf_counter() - start
            content_type = None
            try:
                content_type = response.headers.get('content-type')
            except Exception:
                content_type = None
            print(
                f"[auth-manual] http_post_done url={url} status={getattr(response, 'status_code', None)} "
                f"elapsed={elapsed:.2f}s content_type={content_type}"
            )
            if url.endswith('/backend-api/f/conversation') and not kwargs.get('stream', False):
                try:
                    preview = response.text[:300]
                    print(f"[auth-manual] conversation_response_preview={preview}")
                except Exception as exc:
                    print(f"[auth-manual] conversation_response_preview_error={exc}")
            return response
        except Exception as exc:
            elapsed = perf_counter() - start
            print(f"[auth-manual] http_post_failed url={url} elapsed={elapsed:.2f}s error={exc}")
            raise

    client.session.post = traced_post


def attach_stage_tracing(client: ChatTransport) -> None:
    if not isinstance(client, ChatGPT):
        return
    stage_names = [
        '_authenticated_prepare_conversation',
        '_authenticated_chat_requirements',
        '_authenticated_send_initial',
        '_authenticated_stream_initial',
        '_authenticated_upload_file',
    ]

    for name in stage_names:
        if not hasattr(client, name):
            continue
        original = getattr(client, name)

        def make_wrapper(fn_name, fn):
            def wrapper(*args, **kwargs):
                start = perf_counter()
                print(f"[auth-manual] stage_start={fn_name}")
                try:
                    result = fn(*args, **kwargs)
                    elapsed = perf_counter() - start
                    print(f"[auth-manual] stage_done={fn_name} elapsed={elapsed:.2f}s")
                    return result
                except Exception as exc:
                    elapsed = perf_counter() - start
                    print(f"[auth-manual] stage_failed={fn_name} elapsed={elapsed:.2f}s error={exc}")
                    raise
            return wrapper

        setattr(client, name, make_wrapper(name, original))


def load_discovered_cookies(path: str = "session.discovered.json") -> dict[str, str]:
    payload = load_json(path)
    cookies = payload.get("cookies")
    return cookies if isinstance(cookies, dict) else {}


def main() -> None:
    raw_session = load_json("session.json")
    session_data = merge_browser_settings(raw_session, raw_session.get("browser_settings_path", "browser-settings.json"))
    transport_mode = (session_data.get("transport_mode") or "authenticated").strip().lower()
    all_cookies = parse_netscape_cookies_txt("cookies.txt")
    if not all_cookies:
        discovery_path = session_data.get("websocket_discovery_path", "session.discovered.json")
        all_cookies = load_discovered_cookies(discovery_path)
    selected_cookies = select_authenticated_cookies(all_cookies)
    cookie_summary = summarize_cookies(selected_cookies)

    print(f"[auth-manual] transport_mode={transport_mode}")
    print(f"[auth-manual] selected_cookie_count={cookie_summary['count']}")
    print(f"[auth-manual] cookie_names={', '.join(cookie_summary['names']) or '-'}")
    print(
        f"[auth-manual] has_session_token={cookie_summary['has_session_token']} "
        f"has_oai_did={cookie_summary['has_oai_did']} "
        f"has_oai_is={cookie_summary['has_oai_is']} "
        f"has_oai_sc={cookie_summary['has_oai_sc']} "
        f"has_cf_clearance={cookie_summary['has_cf_clearance']}"
    )

    if transport_mode != "playwright" and not selected_cookies:
        raise RuntimeError("No ChatGPT/OpenAI authenticated cookies were found in cookies.txt")

    if transport_mode == "playwright":
        print(
            f"[auth-manual] playwright_profile user_data_dir={session_data.get('browser_user_data_dir') or session_data.get('user_data_dir')} "
            f"profile_directory={session_data.get('browser_profile_directory') or session_data.get('profile_directory')}"
        )
        print(
            f"[auth-manual] playwright_cdp connect_over_cdp={bool(session_data.get('browser_connect_over_cdp', False))} "
            f"cdp_url={session_data.get('browser_cdp_url')} auto_start_debug_browser={bool(session_data.get('browser_auto_start_debug_browser', False))} "
            f"debugging_port={session_data.get('browser_debugging_port')}"
        )

    client = build_authenticated_client(session_data, selected_cookies)
    manual_started = perf_counter()
    if hasattr(client, "event_callback"):
        def _log_playwright_event(event: dict[str, Any]):
            local_elapsed = perf_counter() - manual_started
            stage = event.get("stage")
            elapsed_ms = event.get("elapsed_ms")
            print(f"[auth-manual] playwright_event local_elapsed={local_elapsed:.2f}s transport_elapsed_ms={elapsed_ms} stage={stage} payload={event}")
        client.event_callback = _log_playwright_event
    attach_http_tracing(client, conversation_timeout_seconds=session_data.get('conversation_timeout_seconds'))
    attach_stage_tracing(client)
    print(f"[auth-manual] session_status={client.get_session_status()}")
    print(f"[auth-manual] transport_audit={client.get_transport_audit()}")
    print(f"[auth-manual] websocket_url_supplied={bool(getattr(client, 'websocket_url', None))}")

    message = session_data.get("message", "Test authenticated flow")
    print(f"[auth-manual] message={message!r}")

    try:
        started = perf_counter()
        result = client.send_message(message, None, new_conversation=True)
        print(f"[auth-manual] total_elapsed={perf_counter() - started:.2f}s")
        print(f"[auth-manual] transport_details={result.transport_details}")
        print("[auth-manual] response_start")
        print(result.text)
        print("[auth-manual] response_end")
    except Exception as exc:
        print(f"[auth-manual] request_failed={exc}")
        print(f"[auth-manual] debug_summary={client.get_debug_summary()}")
        raise


if __name__ == "__main__":
    main()
