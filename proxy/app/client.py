from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator


class ProxyNotImplementedError(RuntimeError):
    pass


@dataclass(slots=True)
class ProxyModelInfo:
    id: str
    owned_by: str = "chatgpt-wrapper"


SUPPORTED_MODELS = [
    ProxyModelInfo("chatgpt-playwright"),
    ProxyModelInfo("chatgpt-authenticated"),
]


def list_models() -> list[ProxyModelInfo]:
    return list(SUPPORTED_MODELS)


async def stream_chat_completion(*, model: str, messages: list[dict]) -> AsyncIterator[str]:
    raise ProxyNotImplementedError("Direct ChatGPT runtime integration is not implemented yet")
    yield ""


def complete_chat(*, model: str, messages: list[dict]) -> str:
    raise ProxyNotImplementedError("Direct ChatGPT runtime integration is not implemented yet")
