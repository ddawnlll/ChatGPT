from pathlib import Path
from subprocess import run
from time import perf_counter

import manual_authenticated as shared
from wrapper.paths import get_default_browser_executable_path, get_default_browser_user_data_dir


def refresh_hybrid_session_material(session_data: dict) -> dict:
    discovery_path = session_data.get("websocket_discovery_path", "session.discovered.json")
    command = [
        "bun",
        "tools/extract_authenticated_session.mjs",
        "--output",
        discovery_path,
        "--url",
        session_data.get("browser_chat_url", "https://chatgpt.com/"),
        "--channel",
        session_data.get("browser_channel") or "",
        "--user-data-dir",
        session_data.get("browser_user_data_dir") or session_data.get("user_data_dir") or get_default_browser_user_data_dir(),
        "--profile-directory",
        session_data.get("browser_profile_directory") or session_data.get("profile_directory") or "Default",
        "--cdp-url",
        session_data.get("browser_cdp_url", "http://127.0.0.1:9222"),
        "--debugging-port",
        str(session_data.get("browser_debugging_port", 9222)),
    ]
    if not session_data.get("browser_auto_start_debug_browser", False):
        command.append("--no-auto-start-debug-browser")
    if not session_data.get("browser_connect_over_cdp", True):
        command.append("--no-cdp")

    print(f"[auth-hybrid] extractor_start command={' '.join(command)}")
    import os
    env = os.environ.copy()
    project_root = Path(__file__).parent.resolve()
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(project_root / "bin" / "browsers")
    
    completed = run(command, check=False, env=env)
    print(f"[auth-hybrid] extractor_done returncode={completed.returncode}")
    if completed.returncode != 0:
        raise RuntimeError(f"Hybrid extractor failed with return code {completed.returncode}")
    discovered = shared.load_json(discovery_path)
    print(f"[auth-hybrid] discovered_cookie_count={len((discovered.get('cookies') or {}))}")
    print(f"[auth-hybrid] discovered_websocket_url_present={bool(discovered.get('websocket_url'))}")
    return discovered


def main() -> None:
    raw_session = shared.load_json("session.json")
    session_data = shared.merge_browser_settings(raw_session, raw_session.get("browser_settings_path", "browser-settings.json"))
    session_data["transport_mode"] = "authenticated"

    discovered = refresh_hybrid_session_material(session_data)
    all_cookies = dict(discovered.get("cookies") or {})
    if not all_cookies:
        all_cookies = shared.parse_netscape_cookies_txt("cookies.txt")
    selected_cookies = shared.select_authenticated_cookies(all_cookies)
    if discovered.get("websocket_url"):
        session_data["websocket_url"] = discovered.get("websocket_url")
    if discovered.get("resume_conversation_token"):
        session_data["websocket_verify_token"] = discovered.get("resume_conversation_token")
    cookie_summary = shared.summarize_cookies(selected_cookies)

    print("[auth-hybrid] transport_mode=authenticated")
    print(f"[auth-hybrid] selected_cookie_count={cookie_summary['count']}")
    print(f"[auth-hybrid] cookie_names={', '.join(cookie_summary['names']) or '-'}")
    print(
        f"[auth-hybrid] has_session_token={cookie_summary['has_session_token']} "
        f"has_oai_did={cookie_summary['has_oai_did']} "
        f"has_oai_is={cookie_summary['has_oai_is']} "
        f"has_oai_sc={cookie_summary['has_oai_sc']} "
        f"has_cf_clearance={cookie_summary['has_cf_clearance']}"
    )

    if not selected_cookies:
        raise RuntimeError("No ChatGPT/OpenAI authenticated cookies were found in cookies.txt or session.discovered.json")

    client = shared.build_authenticated_client(session_data, selected_cookies)
    shared.attach_http_tracing(client, conversation_timeout_seconds=session_data.get('conversation_timeout_seconds'))
    shared.attach_stage_tracing(client)
    print(f"[auth-hybrid] session_status={client.get_session_status()}")
    print(f"[auth-hybrid] transport_audit={client.get_transport_audit()}")
    print(f"[auth-hybrid] websocket_url_supplied={bool(getattr(client, 'websocket_url', None))}")

    message = session_data.get("message", "Test authenticated hybrid flow")
    print(f"[auth-hybrid] message={message!r}")

    try:
        started = perf_counter()
        result = client.send_message(message, None, new_conversation=True)
        print(f"[auth-hybrid] total_elapsed={perf_counter() - started:.2f}s")
        print(f"[auth-hybrid] transport_details={result.transport_details}")
        print("[auth-hybrid] response_start")
        print(result.text)
        print("[auth-hybrid] response_end")
    except Exception as exc:
        print(f"[auth-hybrid] request_failed={exc}")
        print(f"[auth-hybrid] debug_summary={client.get_debug_summary()}")
        raise


if __name__ == "__main__":
    main()
