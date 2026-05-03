from __future__ import annotations

import json
import time
import uuid
from typing import AsyncGenerator, Iterable


def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


def done_sse() -> str:
    return "data: [DONE]\n\n"


async def chat_completions_stream(generator: AsyncGenerator[str, None] | Iterable[str], model: str, request_id: str | None = None):
    created = int(time.time())
    req_id = request_id or f"chatcmpl-{uuid.uuid4().hex}"
    emitted_any = False

    if hasattr(generator, "__aiter__"):
        async for chunk in generator:  # type: ignore[union-attr]
            text = str(chunk or "")
            if not text:
                continue
            delta = {"content": text}
            if not emitted_any:
                delta = {"role": "assistant", "content": text}
                emitted_any = True
            yield sse({
                "id": req_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            })
    else:
        for chunk in generator:  # type: ignore[not-an-iterable]
            text = str(chunk or "")
            if not text:
                continue
            delta = {"content": text}
            if not emitted_any:
                delta = {"role": "assistant", "content": text}
                emitted_any = True
            yield sse({
                "id": req_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            })

    yield sse({
        "id": req_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    })
    yield done_sse()
