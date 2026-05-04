from __future__ import annotations

import time
import uuid
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from .client import complete_chat, complete_chat_turn, list_models, stream_chat_completion
from .config import settings
from .models import ChatChoice, ChatRequest, ChatResponse, ChatResponseMessage, ChatUsage, HealthResponse, ModelList, StreamChoice, StreamChunk, StreamDelta
from .streaming import chat_completions_stream, done_sse, sse
from .tools_shim import (
    ParsedAssistantAction,
    build_openai_tool_call,
    build_pi_agent_prompt,
    build_tool_repair_prompt,
    is_pi_agent_request,
    parse_assistant_action,
    should_retry_malformed_tool_call,
)

router = APIRouter()
logger = logging.getLogger("chatgpt_proxy.router")

STREAM_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def openai_error(message: str, status_code: int, code: str | None = None) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "error": {
                "message": message,
                "type": "invalid_request_error" if status_code < 500 else "server_error",
                "code": code,
            }
        },
    )


@router.get("/health", response_model=HealthResponse)
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "api_key_auth_enabled": bool(settings.api_key),
        "model_count": len(list_models()),
        "default_transport_mode": "playwright",
    }


@router.get("/v1/models", response_model=ModelList)
async def get_models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": model.id,
                "object": "model",
                "created": 0,
                "owned_by": model.owned_by,
            }
            for model in list_models()
        ],
    }


def tool_parse_error_message(parse_error: str | None) -> str:
    detail = f": {parse_error}" if parse_error else ""
    return f"Model emitted a malformed tool call{detail}"


def action_tool_calls(action: Any) -> list[dict[str, Any]]:
    if getattr(action, "kind", None) == "tools" and getattr(action, "tool_calls", None):
        return [build_openai_tool_call(call.name, call.arguments) for call in action.tool_calls]
    if getattr(action, "kind", None) == "tool" and getattr(action, "tool_name", None) and isinstance(getattr(action, "tool_arguments", None), dict):
        return [build_openai_tool_call(action.tool_name, action.tool_arguments)]
    return []


def is_placeholder_transport_artifact(text: str) -> bool:
    raw = str(text or "").strip().lower()
    return raw in {
        "<tool_call>...</tool_call>",
        "<final_response>...</final_response>",
    }



def extract_latest_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if str(message.get("role", "")).strip().lower() != "user":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                    parts.append(item["text"].strip())
            text = "\n".join(part for part in parts if part).strip()
            if text:
                return text
    return ""



def request_requires_write_tool(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> bool:
    tool_names = {tool.get("function", {}).get("name") for tool in (tools or []) if isinstance(tool, dict) and isinstance(tool.get("function"), dict)}
    if "write" not in tool_names:
        return False
    if any(str(message.get("role", "")).strip().lower() == "tool" for message in messages if isinstance(message, dict)):
        return False
    latest_user_text = extract_latest_user_text(messages).lower()
    if not latest_user_text:
        return False
    write_signals = (
        "create ",
        "write ",
        "create file",
        "write file",
        "save ",
        "make file",
        ".py",
        ".js",
        ".ts",
        ".json",
        ".md",
    )
    return any(signal in latest_user_text for signal in write_signals)



def is_tool_access_refusal_text(text: str) -> bool:
    raw = str(text or "").strip().lower().replace("’", "'").replace("`", "'")
    return any(
        token in raw
        for token in (
            "i don't have access",
            "i do not have access",
            "i can't access",
            "i cannot access",
            "no access to the",
            "no access to pi",
            "don't have access to the pi",
            "cannot create",
            "can't create",
        )
    )



def build_tool_access_recovery_prompt(base_prompt: str, *, require_write: bool) -> str:
    prompt = base_prompt.rstrip()
    prompt += (
        "\n\nRecovery rule:\n"
        "Your previous reply incorrectly claimed you lacked tool access. That was wrong.\n"
        "In this environment, you DO have access through the provided pi tools.\n"
        "Do not output prose, apologies, or access disclaimers on this turn.\n"
    )
    if require_write:
        prompt += (
            "The current task requires the write tool.\n"
            "Emit exactly one write tool_call now.\n"
            "Include the file path in <path> and wrap the exact file body in exactly one fenced code block inside <write_content>.\n"
            "Do not emit <final_response>.\n"
        )
    else:
        prompt += "If the user's task requires a tool, emit the needed tool_call now.\n"
    return prompt



def resolve_agent_action(*, model: str, dumped_messages: list[dict[str, Any]], conversation_id: str | None, prompt_override: str | None, require_write: bool = False) -> tuple[str, Any]:
    text, effective_conversation_id = complete_chat_turn(
        model=model,
        messages=dumped_messages,
        conversation_id=conversation_id,
        prompt_override=prompt_override,
    )
    logger.warning("assistant_raw_text_before_parse=%r", text)
    action = parse_assistant_action(text)
    logger.warning(
        "assistant_parsed_action kind=%s tool_name=%s parse_error=%r",
        getattr(action, "kind", None),
        getattr(action, "tool_name", None),
        getattr(action, "parse_error", None),
    )
    if is_placeholder_transport_artifact(text):
        return text, ParsedAssistantAction(kind="invalid_tool", parse_error="placeholder transport artifact")
    if action.kind == "final" and is_tool_access_refusal_text(text):
        recovery_prompt = build_tool_access_recovery_prompt(prompt_override or extract_latest_user_text(dumped_messages), require_write=require_write)
        recovered_text = complete_chat(
            model=model,
            messages=dumped_messages,
            conversation_id=effective_conversation_id,
            prompt_override=recovery_prompt,
        )
        logger.warning("assistant_recovered_raw_text_before_parse=%r", recovered_text)
        recovered_action = parse_assistant_action(recovered_text)
        logger.warning(
            "assistant_recovered_parsed_action kind=%s tool_name=%s parse_error=%r",
            getattr(recovered_action, "kind", None),
            getattr(recovered_action, "tool_name", None),
            getattr(recovered_action, "parse_error", None),
        )
        return recovered_text, recovered_action
    if should_retry_malformed_tool_call(action):
        repair_prompt = build_tool_repair_prompt(text, action.parse_error)
        repaired_text = complete_chat(
            model=model,
            messages=dumped_messages,
            conversation_id=effective_conversation_id,
            prompt_override=repair_prompt,
        )
        logger.warning("assistant_repaired_raw_text_before_parse=%r", repaired_text)
        repaired_action = parse_assistant_action(repaired_text)
        logger.warning(
            "assistant_repaired_parsed_action kind=%s tool_name=%s parse_error=%r",
            getattr(repaired_action, "kind", None),
            getattr(repaired_action, "tool_name", None),
            getattr(repaired_action, "parse_error", None),
        )
        return repaired_text, repaired_action
    return text, action


@router.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest, raw_request: Request):
    logger.info("Received chat completions request for model: %s", request.model)
    if not request.messages:
        raise openai_error("messages must not be empty", 400, "invalid_messages")

    model_ids = {model.id for model in list_models()}
    if request.model not in model_ids:
        raise openai_error(f"Unknown model: {request.model}", 400, "model_not_found")

    conversation_id = request.user.strip() if isinstance(request.user, str) and request.user.strip() else None
    dumped_messages = [message.model_dump() for message in request.messages]
    agent_mode = is_pi_agent_request(request.tools)
    prompt_override = None
    require_write = False
    if agent_mode:
        decision = build_pi_agent_prompt(dumped_messages, request.tools)
        prompt_override = decision.prompt
        require_write = request_requires_write_tool(dumped_messages, request.tools)
        if require_write:
            prompt_override += (
                "\n\nRequest classification: write_required.\n"
                "The user's current task requires the write tool.\n"
                "Emit exactly one write tool_call on this turn.\n"
                "Do not answer with prose or claim you lack tool access.\n"
                "Put the destination file path in <path> and wrap the exact file body in exactly one fenced code block inside <write_content>.\n"
                "Do not emit <final_response> on this turn.\n"
            )
        if request.parallel_tool_calls is True:
            prompt_override += (
                "\n\nRequest option: parallel_tool_calls=true.\n"
                "When safe, batch independent read-only inspection tool calls in one response.\n"
            )
        if request.tool_choice == "required":
            prompt_override += (
                "\n\nRequest option: tool_choice=required.\n"
                "You must emit at least one tool_call. Do not emit final_response on this turn.\n"
            )

    if request.stream:
        if agent_mode:
            async def agent_event_stream():
                req_id = f"chatcmpl-{uuid.uuid4().hex}"
                created = int(time.time())
                try:
                    text, action = resolve_agent_action(
                        model=request.model,
                        dumped_messages=dumped_messages,
                        conversation_id=conversation_id,
                        prompt_override=prompt_override,
                        require_write=require_write,
                    )
                except ValueError as exc:
                    yield sse({"error": {"message": str(exc), "type": "invalid_request_error", "code": "invalid_messages"}})
                    yield done_sse()
                    return
                except Exception as exc:
                    yield sse({"error": {"message": str(exc), "type": "server_error", "code": "transport_error"}})
                    yield done_sse()
                    return
                tool_calls = action_tool_calls(action)
                if tool_calls:
                    chunk = StreamChunk(
                        id=req_id,
                        created=created,
                        model=request.model,
                        choices=[StreamChoice(index=0, delta=StreamDelta(role="assistant", tool_calls=tool_calls), finish_reason="tool_calls")],
                    )
                    yield sse(chunk.model_dump())
                    yield done_sse()
                    return
                if action.kind == "invalid_tool":
                    yield sse({"error": {"message": tool_parse_error_message(action.parse_error), "type": "server_error", "code": "malformed_tool_call"}})
                    yield done_sse()
                    return
                content = action.content or ""
                first_chunk = StreamChunk(
                    id=req_id,
                    created=created,
                    model=request.model,
                    choices=[StreamChoice(index=0, delta=StreamDelta(role="assistant", content=content), finish_reason=None)],
                )
                yield sse(first_chunk.model_dump())
                end_chunk = StreamChunk(
                    id=req_id,
                    created=created,
                    model=request.model,
                    choices=[StreamChoice(index=0, delta=StreamDelta(), finish_reason="stop")],
                )
                yield sse(end_chunk.model_dump())
                yield done_sse()

            return StreamingResponse(agent_event_stream(), media_type="text/event-stream", headers=STREAM_HEADERS)

        async def event_stream():
            try:
                upstream = stream_chat_completion(
                    model=request.model,
                    messages=dumped_messages,
                    conversation_id=conversation_id,
                    prompt_override=prompt_override,
                )
                async for item in chat_completions_stream(upstream, request.model):
                    yield item
            except ValueError as exc:
                yield sse({"error": {"message": str(exc), "type": "invalid_request_error", "code": "invalid_messages"}})
                yield done_sse()
                return
            except Exception as exc:
                yield sse({"error": {"message": str(exc), "type": "server_error", "code": "transport_error"}})
                yield done_sse()
                return

        return StreamingResponse(event_stream(), media_type="text/event-stream", headers=STREAM_HEADERS)

    try:
        if agent_mode:
            text, action = resolve_agent_action(
                model=request.model,
                dumped_messages=dumped_messages,
                conversation_id=conversation_id,
                prompt_override=prompt_override,
                require_write=require_write,
            )
        else:
            text = complete_chat(model=request.model, messages=dumped_messages, conversation_id=conversation_id, prompt_override=prompt_override)
            action = None
    except ValueError as exc:
        raise openai_error(str(exc), 400, "invalid_messages") from exc

    if agent_mode:
        tool_calls = action_tool_calls(action)
        if tool_calls:
            payload = ChatResponse(
                id=f"chatcmpl-{uuid.uuid4().hex}",
                created=int(time.time()),
                model=request.model,
                choices=[
                    ChatChoice(
                        index=0,
                        message=ChatResponseMessage(role="assistant", content=None, tool_calls=tool_calls),
                        finish_reason="tool_calls",
                    )
                ],
                usage=ChatUsage(),
            )
            return payload.model_dump()
        if action.kind == "invalid_tool":
            raise openai_error(tool_parse_error_message(action.parse_error), 502, "malformed_tool_call")
        text = action.content or ""

    payload = ChatResponse(
        id=f"chatcmpl-{uuid.uuid4().hex}",
        created=int(time.time()),
        model=request.model,
        choices=[
            ChatChoice(
                index=0,
                message=ChatResponseMessage(role="assistant", content=text),
                finish_reason="stop",
            )
        ],
        usage=ChatUsage(),
    )
    return payload.model_dump()
