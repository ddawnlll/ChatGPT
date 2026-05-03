from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(slots=True)
class Settings:
    host: str = field(default_factory=lambda: os.environ.get("CHATGPT_PROXY_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.environ.get("CHATGPT_PROXY_PORT", "8080")))
    debug: bool = field(default_factory=lambda: os.environ.get("CHATGPT_PROXY_DEBUG", "false").lower() in {"1", "true", "yes", "on"})
    api_key: str = field(default_factory=lambda: os.environ.get("CHATGPT_PROXY_API_KEY", ""))


settings = Settings()
