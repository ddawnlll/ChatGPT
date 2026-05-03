from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from json import dumps, loads
from typing import Any, AsyncIterator
from uuid import uuid4

from transport_runtime import ChatTransport, build_transport

from .config import settings
from .state import ConversationState, conversation_store
from .tools_shim import parse_assistant_action


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


def _normalize_tool_calls(tool_calls: Any) -> list[dict[str, Any]] | None:
    if not isinstance(tool_calls, list):
        return None
    normalized: list[dict[str, Any]] = []
    for tool_call in tool_calls:
        if not isinstance(tool_call, dict):
            continue
        function = tool_call.get("function") or {}
        if not isinstance(function, dict):
            function = {}
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = dumps(loads(arguments), ensure_ascii=False, sort_keys=True)
            except Exception:
                arguments = arguments.strip()
        normalized.append({
            "type": tool_call.get("type"),
            "name": function.get("name") or tool_call.get("name"),
            "arguments": arguments,
        })
    return normalized


def fingerprint_messages(messages: list[dict[str, Any]]) -> str:
    normalized: list[dict[str, Any]] = []
    for message in messages:
        # Ignore system messages because they often contain dynamic timestamps or context
        if str(message.get("role", "")).strip().lower() == "system":
            continue
        tool_call_id = message.get("tool_call_id")
        normalized.append({
            "role": str(message.get("role", "")).strip(),
            "content": message.get("content"),
            "tool_calls": _normalize_tool_calls(message.get("tool_calls")),
            "tool_call_id": tool_call_id.strip() if isinstance(tool_call_id, str) and tool_call_id.strip() else None,
            "name": message.get("name"),
        })
    if not normalized:
        return ""
    return sha256(dumps(normalized, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


class RuntimeClient:
    def __init__(self, model_id: str):
        self.model_id = model_id

    def _resolve_state(self, conversation_id: str | None, messages: list[dict[str, Any]]) -> tuple[str | None, ConversationState | None]:
        if conversation_id:
            return conversation_id, conversation_store.get(conversation_id)

        history_messages = messages[:-1] if len(messages) > 1 else []
        history_alias = fingerprint_messages(history_messages)
        if history_alias:
            state = conversation_store.get_by_history_alias(history_alias)
            if state is not None:
                return state.conversation_id, state
        return None, None

    def _get_transport(self, conversation_id: str | None, messages: list[dict[str, Any]]) -> tuple[ChatTransport, bool, ConversationState | None, str | None]:
        resolved_conversation_id, state = self._resolve_state(conversation_id, messages)
        if state and state.transport is not None:
            return state.transport, False, state, resolved_conversation_id

        transport = build_transport(build_session_material(self.model_id))
        effective_conversation_id = resolved_conversation_id or conversation_id or f"proxy-{uuid4().hex}"
        state = state or ConversationState(conversation_id=effective_conversation_id)
        transport_data = getattr(transport, "data", None)
        if isinstance(transport_data, dict):
            if state.data.get("remote_conversation_id"):
                transport_data["conversation_id"] = state.data.get("remote_conversation_id")
            if state.data.get("remote_parent_message_id"):
                transport_data["parent_message_id"] = state.data.get("remote_parent_message_id")
        state.transport = transport
        conversation_store.put(state)
        return transport, state.data.get("remote_conversation_id") is None, state, effective_conversation_id

    def _update_state_after_response(self, state: ConversationState | None, messages: list[dict[str, Any]], assistant_text: str, remote_conversation_id: str | None, remote_parent_message_id: str | None) -> None:
        if state is None:
            return
        state.data["remote_conversation_id"] = remote_conversation_id
        state.data["remote_parent_message_id"] = remote_parent_message_id
        history_alias = fingerprint_messages(messages)
        transcript_aliases = [fingerprint_messages([*messages, {"role": "assistant", "content": assistant_text}])]

        action = parse_assistant_action(assistant_text)
        if action.kind == "tool" and action.tool_name and isinstance(action.tool_arguments, dict):
            transcript_aliases.append(
                fingerprint_messages(
                    [
                        *messages,
                        {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "type": "function",
                                    "function": {
                                        "name": action.tool_name,
                                        "arguments": dumps(action.tool_arguments, ensure_ascii=False, sort_keys=True),
                                    },
                                }
                            ],
                        },
                    ]
                )
            )
        elif action.kind == "final":
            transcript_aliases.append(fingerprint_messages([*messages, {"role": "assistant", "content": action.content or ""}]))

        conversation_store.put(state)
        conversation_store.bind_history_alias(history_alias, state.conversation_id)
        for transcript_alias in transcript_aliases:
            conversation_store.bind_history_alias(transcript_alias, state.conversation_id)

    def complete_chat_turn(self, *, messages: list[dict[str, Any]], conversation_id: str | None = None, prompt_override: str | None = None) -> tuple[str, str | None]:
        prompt = prompt_override or extract_latest_user_text(messages)
        if not prompt:
            raise ValueError("No user message content was found")
        transport, new_conversation, state, effective_conversation_id = self._get_transport(conversation_id, messages)
        result = transport.send_message(prompt, None, new_conversation=new_conversation)
        self._update_state_after_response(state, messages, result.text, result.remote_conversation_id, result.remote_parent_message_id)
        return result.text, effective_conversation_id

    def complete_chat(self, *, messages: list[dict[str, Any]], conversation_id: str | None = None, prompt_override: str | None = None) -> str:
        text, _effective_conversation_id = self.complete_chat_turn(
            messages=messages,
            conversation_id=conversation_id,
            prompt_override=prompt_override,
        )
        return text

    async def stream_chat(self, *, messages: list[dict[str, Any]], conversation_id: str | None = None, prompt_override: str | None = None) -> AsyncIterator[str]:
        prompt = prompt_override or extract_latest_user_text(messages)
        if not prompt:
            raise ValueError("No user message content was found")
        transport, new_conversation, state, _effective_conversation_id = self._get_transport(conversation_id, messages)
        chunks: list[str] = []
        for chunk in transport.stream_message(prompt, None, new_conversation=new_conversation):
            text = str(chunk or "")
            if not text:
                continue
            chunks.append(text)
            yield text
        result = transport.get_last_result()
        self._update_state_after_response(state, messages, result.text or "".join(chunks), result.remote_conversation_id, result.remote_parent_message_id)


def complete_chat(*, model: str, messages: list[dict[str, Any]], conversation_id: str | None = None, prompt_override: str | None = None) -> str:
    return RuntimeClient(model).complete_chat(messages=messages, conversation_id=conversation_id, prompt_override=prompt_override)


def complete_chat_turn(*, model: str, messages: list[dict[str, Any]], conversation_id: str | None = None, prompt_override: str | None = None) -> tuple[str, str | None]:
    return RuntimeClient(model).complete_chat_turn(messages=messages, conversation_id=conversation_id, prompt_override=prompt_override)


async def stream_chat_completion(*, model: str, messages: list[dict[str, Any]], conversation_id: str | None = None, prompt_override: str | None = None) -> AsyncIterator[str]:
    async for chunk in RuntimeClient(model).stream_chat(messages=messages, conversation_id=conversation_id, prompt_override=prompt_override):
        yield chunk
