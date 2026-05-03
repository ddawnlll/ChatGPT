from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator

from transport_runtime import ChatTransport, build_transport

from .config import settings
from .state import ConversationState, conversation_store


@dataclass(slots=True)
class ProxyModelInfo:
    id: str
    owned_by: str = "chatgpt-wrapper"
    transport_mode: str = "playwright"
    thinking_mode: str = "extended"
    model_name: str = "auto"
    reasoning: bool = True
    input: tuple[str, ...] = ("text",)
    context_window: int = 128000
    max_tokens: int = 16384


SUPPORTED_MODELS = [
    ProxyModelInfo("chatgpt-playwright", transport_mode="playwright", thinking_mode="extended", model_name="auto"),
    ProxyModelInfo("chatgpt-authenticated", transport_mode="authenticated", thinking_mode="extended", model_name="auto"),
]
MODEL_MAP = {model.id: model for model in SUPPORTED_MODELS}


def list_models() -> list[ProxyModelInfo]:
    return list(SUPPORTED_MODELS)


def resolve_model(model_id: str) -> ProxyModelInfo:
    if model_id not in MODEL_MAP:
        raise KeyError(model_id)
    return MODEL_MAP[model_id]


def _extract_message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return "\n".join(parts).strip()
    return ""


def extract_latest_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if str(message.get("role", "")).strip() != "user":
            continue
        text = _extract_message_text(message)
        if text:
            return text
    return ""


def build_session_material(model_id: str) -> dict[str, Any]:
    model = resolve_model(model_id)
    session_material = settings.session_material()
    session_material["transport_mode"] = model.transport_mode
    session_material["thinking_mode"] = model.thinking_mode
    session_material["model_name"] = model.model_name
    return session_material


class RuntimeClient:
    def __init__(self, model_id: str):
        self.model_id = model_id

    def _get_transport(self, conversation_id: str | None) -> tuple[ChatTransport, bool, ConversationState | None]:
        if conversation_id:
            state = conversation_store.get(conversation_id)
            if state and state.transport is not None:
                return state.transport, False, state

        transport = build_transport(build_session_material(self.model_id))
        if conversation_id:
            state = conversation_store.get(conversation_id) or ConversationState(conversation_id=conversation_id)
            state.transport = transport
            conversation_store.put(state)
            return transport, True, state
        return transport, True, None

    def complete_chat(self, *, messages: list[dict[str, Any]], conversation_id: str | None = None) -> str:
        prompt = extract_latest_user_text(messages)
        if not prompt:
            raise ValueError("No user message content was found")
        transport, new_conversation, state = self._get_transport(conversation_id)
        result = transport.send_message(prompt, None, new_conversation=new_conversation)
        if state is not None:
            state.data["remote_conversation_id"] = result.remote_conversation_id
            state.data["remote_parent_message_id"] = result.remote_parent_message_id
            conversation_store.put(state)
        return result.text

    async def stream_chat(self, *, messages: list[dict[str, Any]], conversation_id: str | None = None) -> AsyncIterator[str]:
        prompt = extract_latest_user_text(messages)
        if not prompt:
            raise ValueError("No user message content was found")
        transport, new_conversation, state = self._get_transport(conversation_id)
        chunks: list[str] = []
        for chunk in transport.stream_message(prompt, None, new_conversation=new_conversation):
            text = str(chunk or "")
            if not text:
                continue
            chunks.append(text)
            yield text
        if state is not None:
            result = transport.get_last_result()
            state.data["remote_conversation_id"] = result.remote_conversation_id
            state.data["remote_parent_message_id"] = result.remote_parent_message_id
            state.data["response_preview"] = "".join(chunks)[:200]
            conversation_store.put(state)


def complete_chat(*, model: str, messages: list[dict[str, Any]], conversation_id: str | None = None) -> str:
    return RuntimeClient(model).complete_chat(messages=messages, conversation_id=conversation_id)


async def stream_chat_completion(*, model: str, messages: list[dict[str, Any]], conversation_id: str | None = None) -> AsyncIterator[str]:
    async for chunk in RuntimeClient(model).stream_chat(messages=messages, conversation_id=conversation_id):
        yield chunk
