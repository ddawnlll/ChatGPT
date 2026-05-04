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



def resolve_agent_action(*, model: str, dumped_messages: list[dict[str, Any]], conversation_id: str | None, prompt_override: str | None) -> tuple[str, Any]:
    text, effective_conversation_id = complete_chat_turn(
        model=model,
        messages=dumped_messages,
        conversation_id=conversation_id,
        prompt_override=prompt_override,
    )
    action = parse_assistant_action(text)
    if is_placeholder_transport_artifact(text):
        return text, ParsedAssistantAction(kind="invalid_tool", parse_error="placeholder transport artifact")
    if should_retry_malformed_tool_call(action):
        repair_prompt = build_tool_repair_prompt(text, action.parse_error)
        repaired_text = complete_chat(
            model=model,
            messages=dumped_messages,
            conversation_id=effective_conversation_id,
            prompt_override=repair_prompt,
        )
        repaired_action = parse_assistant_action(repaired_text)
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
    if agent_mode:
        decision = build_pi_agent_prompt(dumped_messages, request.tools)
        prompt_override = decision.prompt
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
