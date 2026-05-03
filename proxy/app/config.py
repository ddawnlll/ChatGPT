from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


def _env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class Settings:
    host: str = field(default_factory=lambda: os.environ.get("CHATGPT_PROXY_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.environ.get("CHATGPT_PROXY_PORT", "8080")))
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
    browser_user_data_dir: str = field(default_factory=lambda: os.environ.get("CHATGPT_PROXY_BROWSER_USER_DATA_DIR", "/home/erfolg/.config/chromium"))
    browser_profile_directory: str = field(default_factory=lambda: os.environ.get("CHATGPT_PROXY_BROWSER_PROFILE_DIRECTORY", "Default"))
    browser_executable_path: str = field(default_factory=lambda: os.environ.get("CHATGPT_PROXY_BROWSER_EXECUTABLE_PATH", "/usr/bin/chromium"))
    browser_channel: str = field(default_factory=lambda: os.environ.get("CHATGPT_PROXY_BROWSER_CHANNEL", ""))
    browser_headless: bool = field(default_factory=lambda: _env_bool("CHATGPT_PROXY_BROWSER_HEADLESS", False))
    browser_chat_url: str = field(default_factory=lambda: os.environ.get("CHATGPT_PROXY_BROWSER_CHAT_URL", "https://chatgpt.com/"))
    browser_capture_timeout_ms: int = field(default_factory=lambda: int(os.environ.get("CHATGPT_PROXY_BROWSER_CAPTURE_TIMEOUT_MS", "120000")))
    browser_connect_over_cdp: bool = field(default_factory=lambda: _env_bool("CHATGPT_PROXY_BROWSER_CONNECT_OVER_CDP", True))
    browser_cdp_url: str = field(default_factory=lambda: os.environ.get("CHATGPT_PROXY_BROWSER_CDP_URL", "http://127.0.0.1:9222"))
    browser_auto_start_debug_browser: bool = field(default_factory=lambda: _env_bool("CHATGPT_PROXY_BROWSER_AUTO_START_DEBUG_BROWSER", True))
    browser_debugging_port: int = field(default_factory=lambda: int(os.environ.get("CHATGPT_PROXY_BROWSER_DEBUGGING_PORT", "9222")))

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
