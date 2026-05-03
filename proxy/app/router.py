from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from .client import complete_chat, list_models, stream_chat_completion
from .config import settings
from .models import ChatChoice, ChatRequest, ChatResponse, ChatResponseMessage, ChatUsage, HealthResponse, ModelList
from .streaming import chat_completions_stream

router = APIRouter()


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


@router.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest):
    if not request.messages:
        raise openai_error("messages must not be empty", 400, "invalid_messages")

    model_ids = {model.id for model in list_models()}
    if request.model not in model_ids:
        raise openai_error(f"Unknown model: {request.model}", 400, "model_not_found")

    conversation_id = request.user.strip() if isinstance(request.user, str) and request.user.strip() else None
    dumped_messages = [message.model_dump() for message in request.messages]

    if request.stream:
        async def event_stream():
            upstream = stream_chat_completion(
                model=request.model,
                messages=dumped_messages,
                conversation_id=conversation_id,
            )
            async for item in chat_completions_stream(upstream, request.model):
                yield item

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    try:
        text = complete_chat(model=request.model, messages=dumped_messages, conversation_id=conversation_id)
    except ValueError as exc:
        raise openai_error(str(exc), 400, "invalid_messages") from exc

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
