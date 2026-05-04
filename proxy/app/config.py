from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _find_system_browser() -> str:
    """Find a system-installed browser. Prefer Chrome, fall back to Brave."""
    candidates = []

    if sys.platform == "darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Firefox.app/Contents/MacOS/firefox",
        ]
    elif sys.platform == "win32":
        candidates = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]
    else:  # Linux
        for name in ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium", "firefox"):
            path = shutil.which(name)
            if path:
                return path

    for path in candidates:
        if os.path.isfile(path):
            return path

    return ""


def _detect_browser_type(executable: str) -> str:
    """Detect browser type from executable path."""
    lower = executable.lower()
    if "firefox" in lower:
        return "firefox"
    return "chromium"


def _default_real_browser_user_data_dir(executable: str) -> str:
    lower = executable.lower()

    if sys.platform == "darwin":
        home = Path.home()
        if "brave" in lower:
            return str((home / "Library/Application Support/BraveSoftware/Brave-Browser").resolve())
        if "chrome" in lower:
            return str((home / "Library/Application Support/Google/Chrome").resolve())
        if "chromium" in lower:
            return str((home / "Library/Application Support/Chromium").resolve())
        if "firefox" in lower:
            return str((home / "Library/Application Support/Firefox").resolve())
    elif sys.platform == "win32":
        if "brave" in lower:
            return os.path.expandvars(r"%LocalAppData%\BraveSoftware\Brave-Browser\User Data")
        if "chrome" in lower:
            return os.path.expandvars(r"%LocalAppData%\Google\Chrome\User Data")
        if "chromium" in lower:
            return os.path.expandvars(r"%LocalAppData%\Chromium\User Data")
        if "firefox" in lower:
            return os.path.expandvars(r"%AppData%\Mozilla\Firefox")
    else:
        home = Path.home()
        if "brave" in lower:
            return str((home / ".config/BraveSoftware/Brave-Browser").resolve())
        if "chrome" in lower:
            return str((home / ".config/google-chrome").resolve())
        if "chromium" in lower:
            return str((home / ".config/chromium").resolve())
        if "firefox" in lower:
            return str((home / ".mozilla/firefox").resolve())

    project_root = Path(__file__).parent.parent.parent
    browser_type = _detect_browser_type(executable)
    profile_name = "firefox_profile" if browser_type == "firefox" else "browser_profile"
    local_profile = project_root / "data" / profile_name
    return str(local_profile.resolve())


def get_default_browser_user_data_dir() -> str:
    executable = os.environ.get("CHATGPT_PROXY_BROWSER_EXECUTABLE_PATH", _find_system_browser())
    return _default_real_browser_user_data_dir(executable)


def _env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class Settings:
    host: str = field(default_factory=lambda: os.environ.get("CHATGPT_PROXY_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.environ.get("CHATGPT_PROXY_PORT", "8081")))
    debug: bool = field(default_factory=lambda: _env_bool("CHATGPT_PROXY_DEBUG", False))
    api_key: str = field(default_factory=lambda: os.environ.get("CHATGPT_PROXY_API_KEY", ""))
    transport_mode: str = field(default_factory=lambda: os.environ.get("CHATGPT_PROXY_TRANSPORT_MODE", "playwright"))
    allow_anon_fallback: bool = field(default_factory=lambda: _env_bool("CHATGPT_PROXY_ALLOW_ANON_FALLBACK", False))
    thinking_mode: str = field(default_factory=lambda: os.environ.get("CHATGPT_PROXY_THINKING_MODE", "extended"))
    model_name: str = field(default_factory=lambda: os.environ.get("CHATGPT_PROXY_MODEL_NAME", "auto"))
    authorization: str = field(default_factory=lambda: os.environ.get("CHATGPT_PROXY_AUTHORIZATION", ""))
    cookies: str = field(default_factory=lambda: os.environ.get("CHATGPT_PROXY_COOKIES", ""))
    websocket_url: str = field(default_factory=lambda: os.environ.get("CHATGPT_PROXY_WEBSOCKET_URL", ""))
    websocket_verify_token: str = field(default_factory=lambda: os.environ.get("CHATGPT_PROXY_WEBSOCKET_VERIFY_TOKEN", ""))
    browser_type: str = field(default_factory=lambda: os.environ.get(
        "CHATGPT_PROXY_BROWSER_TYPE",
        _detect_browser_type(os.environ.get("CHATGPT_PROXY_BROWSER_EXECUTABLE_PATH", _find_system_browser()))
    ))
    browser_user_data_dir: str = field(default_factory=lambda: os.environ.get("CHATGPT_PROXY_BROWSER_USER_DATA_DIR", get_default_browser_user_data_dir()))
    browser_profile_directory: str = field(default_factory=lambda: os.environ.get("CHATGPT_PROXY_BROWSER_PROFILE_DIRECTORY", "Default"))
    browser_executable_path: str = field(default_factory=lambda: os.environ.get("CHATGPT_PROXY_BROWSER_EXECUTABLE_PATH", _find_system_browser()))
    browser_channel: str = field(default_factory=lambda: os.environ.get("CHATGPT_PROXY_BROWSER_CHANNEL", ""))
    browser_headless: bool = field(default_factory=lambda: _env_bool("CHATGPT_PROXY_BROWSER_HEADLESS", False))
    browser_chat_url: str = field(default_factory=lambda: os.environ.get("CHATGPT_PROXY_BROWSER_CHAT_URL", "https://chatgpt.com/"))
    browser_capture_timeout_ms: int = field(default_factory=lambda: int(os.environ.get("CHATGPT_PROXY_BROWSER_CAPTURE_TIMEOUT_MS", "120000")))
    browser_connect_over_cdp: bool = field(default_factory=lambda: _env_bool("CHATGPT_PROXY_BROWSER_CONNECT_OVER_CDP", False))
    browser_cdp_url: str = field(default_factory=lambda: os.environ.get("CHATGPT_PROXY_BROWSER_CDP_URL", "http://127.0.0.1:9222"))
    browser_auto_start_debug_browser: bool = field(default_factory=lambda: _env_bool("CHATGPT_PROXY_BROWSER_AUTO_START_DEBUG_BROWSER", False))
    browser_debugging_port: int = field(default_factory=lambda: int(os.environ.get("CHATGPT_PROXY_BROWSER_DEBUGGING_PORT", "9222")))
    state_dir: str = field(default_factory=lambda: os.environ.get("CHATGPT_PROXY_STATE_DIR", str(Path("data/proxy").resolve())))
    agent_force_new_conversation: bool = field(default_factory=lambda: _env_bool("CHATGPT_PROXY_AGENT_FORCE_NEW_CONVERSATION", True))
    agent_post_tool_final_only: bool = field(default_factory=lambda: _env_bool("CHATGPT_PROXY_AGENT_POST_TOOL_FINAL_ONLY", True))
    agent_local_terminal_final_fastpath: bool = field(default_factory=lambda: _env_bool("CHATGPT_PROXY_AGENT_LOCAL_TERMINAL_FINAL_FASTPATH", True))
    agent_after_tools_plan_enabled: bool = field(default_factory=lambda: _env_bool("CHATGPT_PROXY_AGENT_AFTER_TOOLS_PLAN_ENABLED", True))

    def state_path(self) -> Path:
        path = Path(self.state_dir).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path / "conversation-store.json"

    def session_material(self) -> dict[str, Any]:
        return {
            "transport_mode": self.transport_mode,
            "allow_anon_fallback": self.allow_anon_fallback,
            "thinking_mode": self.thinking_mode,
            "model_name": self.model_name,
            "authorization": self.authorization or None,
            "cookies": self.cookies or None,
            "websocket_url": self.websocket_url or None,
            "websocket_verify_token": self.websocket_verify_token or None,
            "browser_type": self.browser_type,
            "browser_user_data_dir": self.browser_user_data_dir or None,
            "browser_profile_directory": self.browser_profile_directory or None,
            "browser_executable_path": self.browser_executable_path or None,
            "browser_channel": self.browser_channel or None,
            "browser_headless": self.browser_headless,
            "browser_chat_url": self.browser_chat_url or None,
            "browser_capture_timeout_ms": self.browser_capture_timeout_ms,
            "browser_connect_over_cdp": self.browser_connect_over_cdp,
            "browser_cdp_url": self.browser_cdp_url or None,
            "browser_auto_start_debug_browser": self.browser_auto_start_debug_browser,
            "browser_debugging_port": self.browser_debugging_port,
        }


settings = Settings()
