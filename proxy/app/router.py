from __future__ import annotations

import time
import uuid
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from .client import clear_pending_after_tools_plan, complete_chat, complete_chat_turn, get_pending_after_tools_plan, list_models, resolve_conversation_state, stream_chat_completion
from .config import settings
from .models import ChatChoice, ChatRequest, ChatResponse, ChatResponseMessage, ChatUsage, HealthResponse, ModelList, StreamChoice, StreamChunk, StreamDelta
from .streaming import chat_completions_stream, done_sse, sse
from .tools_shim import (
    ParsedAssistantAction,
    build_final_after_tools_prompt,
    build_openai_tool_call,
    build_pi_agent_prompt,
    build_task_continuation_prompt,
    build_tool_failure_recovery_prompt,
    build_tool_repair_prompt,
    count_tool_rounds,
    is_implementation_task,
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
    if getattr(action, "kind", None) in {"tools", "tools_plan"} and getattr(action, "tool_calls", None):
        return [build_openai_tool_call(call.name, call.arguments) for call in action.tool_calls]
    if getattr(action, "kind", None) in {"tool", "tool_plan"} and getattr(action, "tool_name", None) and isinstance(getattr(action, "tool_arguments", None), dict):
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
            "workspace path",
            "not accessible through the available execution tool",
            "not accessible through available execution tool",
            "could not inspect or modify",
            "could not inspect",
            "could not modify",
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



def _find_trailing_post_tool_block(messages: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    if not messages:
        return None
    index = len(messages) - 1
    trailing_tool_messages: list[dict[str, Any]] = []

    while index >= 0:
        message = messages[index]
        role = str(message.get("role", "")).strip().lower() if isinstance(message, dict) else ""
        if role in {"system", "developer"}:
            index -= 1
            continue
        if role == "tool" and isinstance(message, dict):
            trailing_tool_messages.append(message)
            index -= 1
            continue
        break

    if not trailing_tool_messages or index < 0:
        return None

    assistant_message = messages[index]
    if not isinstance(assistant_message, dict):
        return None
    if str(assistant_message.get("role", "")).strip().lower() != "assistant":
        return None
    tool_calls = assistant_message.get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        return None

    trailing_tool_messages.reverse()
    return assistant_message, trailing_tool_messages



def has_tool_results(messages: list[dict[str, Any]]) -> bool:
    return _find_trailing_post_tool_block(messages) is not None



def latest_assistant_tool_calls(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    block = _find_trailing_post_tool_block(messages)
    if block is None:
        return []
    assistant_message, _tool_messages = block
    tool_calls = assistant_message.get("tool_calls")
    return tool_calls if isinstance(tool_calls, list) else []



def _extract_single_terminal_tool_summary(messages: list[dict[str, Any]]) -> tuple[str, dict[str, Any]] | None:
    tool_calls = latest_assistant_tool_calls(messages)
    if len(tool_calls) != 1:
        return None
    tool_call = tool_calls[0]
    function = tool_call.get("function") if isinstance(tool_call, dict) else None
    if not isinstance(function, dict):
        return None
    name = function.get("name")
    if not isinstance(name, str) or not name:
        return None
    arguments_raw = function.get("arguments")
    if isinstance(arguments_raw, str):
        try:
            arguments = json.loads(arguments_raw)
        except Exception:
            return None
    elif isinstance(arguments_raw, dict):
        arguments = arguments_raw
    else:
        return None
    if not isinstance(arguments, dict):
        return None
    return name, arguments



def _looks_like_successful_tool_result(messages: list[dict[str, Any]]) -> bool:
    block = _find_trailing_post_tool_block(messages)
    if block is None:
        return False
    _assistant_message, tool_messages = block
    combined = "\n".join(str(message.get("content", "")) for message in tool_messages).lower()
    failure_markers = (
        "error",
        "failed",
        "failure",
        "traceback",
        "exception",
        "no such file",
        "not found",
        "permission denied",
        "could not find",
        "couldn't find",
        "oldtext must match",
        "must match exactly",
        "no changes made",
        "0 replacements",
        "command exited with code 1",
        "exit code 1",
        "exited with code",
        "indentationerror",
        "syntaxerror",
    )
    return not any(marker in combined for marker in failure_markers)



def should_continue_after_failed_tool(messages: list[dict[str, Any]]) -> bool:
    summary = _extract_single_terminal_tool_summary(messages)
    if summary is None or _looks_like_successful_tool_result(messages):
        return False
    tool_name, _arguments = summary
    return tool_name in {"edit", "bash", "write"}



def render_after_tools_template(template: str, messages: list[dict[str, Any]]) -> str:
    block = _find_trailing_post_tool_block(messages)
    if block is None:
        error_text = ""
    else:
        _assistant_message, tool_messages = block
        error_text = "\n".join(str(message.get("content", "")).strip() for message in tool_messages).strip()
    return template.replace("{error}", error_text)



def is_simple_explicit_bash_request(messages: list[dict[str, Any]]) -> bool:
    latest_user = extract_latest_user_text(messages).lower().strip()
    if not latest_user:
        return False
    explicit_prefixes = (
        "run this command:",
        "run command:",
        "execute this command:",
        "execute command:",
        "run:",
        "execute:",
        "bash:",
        "shell:",
    )
    return latest_user.startswith(explicit_prefixes)



def maybe_synthesize_local_final(messages: list[dict[str, Any]], pending_plan: dict[str, Any] | None = None) -> str | None:
    if pending_plan:
        if _looks_like_successful_tool_result(messages):
            on_success = pending_plan.get("on_success")
            if isinstance(on_success, str) and on_success.strip():
                return render_after_tools_template(on_success.strip(), messages)
        else:
            on_failure = pending_plan.get("on_failure")
            if isinstance(on_failure, str) and on_failure.strip():
                return render_after_tools_template(on_failure.strip(), messages)

    summary = _extract_single_terminal_tool_summary(messages)
    if summary is None or not _looks_like_successful_tool_result(messages):
        return None
    tool_name, arguments = summary
    if tool_name == "write":
        path = arguments.get("path")
        if isinstance(path, str) and path.strip():
            return f"Created {path.strip()}."
    if tool_name == "edit":
        path = arguments.get("path")
        if isinstance(path, str) and path.strip():
            return f"Updated {path.strip()}."
    if tool_name == "bash" and is_simple_explicit_bash_request(messages):
        return "Command completed successfully."
    return None



def resolve_agent_action(*, model: str, dumped_messages: list[dict[str, Any]], conversation_id: str | None, prompt_override: str | None, require_write: bool = False, allow_tool_calls: bool = True, force_new_conversation: bool = False) -> tuple[str, Any]:
    text, effective_conversation_id = complete_chat_turn(
        model=model,
        messages=dumped_messages,
        conversation_id=conversation_id,
        prompt_override=prompt_override,
        force_new_conversation=force_new_conversation,
    )
    action = parse_assistant_action(text)
    if is_placeholder_transport_artifact(text):
        return text, ParsedAssistantAction(kind="invalid_tool", parse_error="placeholder transport artifact")
    if not allow_tool_calls and action_tool_calls(action):
        if should_continue_after_failed_tool(dumped_messages):
            return text, action
        return text, ParsedAssistantAction(kind="invalid_tool", parse_error="tool calls are not allowed after tool results")
    if action.kind == "final" and is_tool_access_refusal_text(text):
        recovery_prompt = build_tool_access_recovery_prompt(prompt_override or extract_latest_user_text(dumped_messages), require_write=require_write)
        recovered_text = complete_chat(
            model=model,
            messages=dumped_messages,
            conversation_id=effective_conversation_id,
            prompt_override=recovery_prompt,
            force_new_conversation=force_new_conversation,
        )
        recovered_action = parse_assistant_action(recovered_text)
        return recovered_text, recovered_action
    if should_retry_malformed_tool_call(action):
        repair_prompt = build_tool_repair_prompt(text, action.parse_error)
        repaired_text = complete_chat(
            model=model,
            messages=dumped_messages,
            conversation_id=effective_conversation_id,
            prompt_override=repair_prompt,
            force_new_conversation=force_new_conversation,
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
    logger.debug("chat_completions conversation identity: has_request_user=%s conversation_id=%s", bool(conversation_id), conversation_id or "<history-alias>")
    dumped_messages = [message.model_dump() for message in request.messages]
    agent_mode = is_pi_agent_request(request.tools)
    prompt_override = None
    require_write = False
    post_tool_turn = False
    allow_tool_calls = True
    force_new_conversation = False
    pending_after_tools_plan: dict[str, Any] | None = None
    resolved_state = None
    task_mode = False
    tool_round_count = 0
    max_tool_rounds = settings.agent_task_max_tool_rounds
    if agent_mode:
        force_new_conversation = settings.agent_force_new_conversation
        task_mode = settings.agent_task_mode_enabled and is_implementation_task(dumped_messages)
        post_tool_turn = settings.agent_post_tool_final_only and has_tool_results(dumped_messages)
        tool_round_count = count_tool_rounds(dumped_messages)
        allow_tool_calls = not post_tool_turn
        if post_tool_turn:
            _resolved_conversation_id, resolved_state = resolve_conversation_state(model=request.model, messages=dumped_messages, conversation_id=conversation_id)
            if settings.agent_after_tools_plan_enabled:
                pending_after_tools_plan = get_pending_after_tools_plan(resolved_state, dumped_messages)
            if should_continue_after_failed_tool(dumped_messages):
                allow_tool_calls = True
                decision = build_tool_failure_recovery_prompt(dumped_messages, request.tools)
                prompt_override = decision.prompt
            elif task_mode and tool_round_count < max_tool_rounds:
                allow_tool_calls = True
                decision = build_task_continuation_prompt(dumped_messages, request.tools, tool_round_count, max_tool_rounds)
                prompt_override = decision.prompt
            else:
                allow_tool_calls = False
                final_prompt_hint = pending_after_tools_plan.get("final_prompt") if isinstance(pending_after_tools_plan, dict) else None
                if task_mode and tool_round_count >= max_tool_rounds:
                    limit_hint = (
                        f"Configured tool-round limit reached ({tool_round_count}/{max_tool_rounds}). "
                        "Return a status update describing what is done, what remains, and any blocker. "
                        "Do not claim success unless the tool evidence proves completion."
                    )
                    final_prompt_hint = f"{final_prompt_hint}\n\n{limit_hint}" if isinstance(final_prompt_hint, str) and final_prompt_hint.strip() else limit_hint
                decision = build_final_after_tools_prompt(dumped_messages, request.tools, final_prompt_hint=final_prompt_hint if isinstance(final_prompt_hint, str) else None)
                prompt_override = decision.prompt
        else:
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

    allow_local_fastpath = settings.agent_local_terminal_final_fastpath and not (task_mode and settings.agent_task_disable_local_bash_fastpath)

    if request.stream:
        if agent_mode:
            async def agent_event_stream():
                req_id = f"chatcmpl-{uuid.uuid4().hex}"
                created = int(time.time())
                try:
                    if post_tool_turn and allow_local_fastpath:
                        synthesized = maybe_synthesize_local_final(dumped_messages, pending_after_tools_plan)
                        if synthesized is not None:
                            if settings.agent_after_tools_plan_enabled:
                                clear_pending_after_tools_plan(resolved_state, dumped_messages)
                            text, action = synthesized, ParsedAssistantAction(kind="final", content=synthesized)
                        else:
                            text, action = resolve_agent_action(
                                model=request.model,
                                dumped_messages=dumped_messages,
                                conversation_id=conversation_id,
                                prompt_override=prompt_override,
                                require_write=require_write,
                                allow_tool_calls=allow_tool_calls,
                                force_new_conversation=force_new_conversation,
                            )
                    else:
                        text, action = resolve_agent_action(
                            model=request.model,
                            dumped_messages=dumped_messages,
                            conversation_id=conversation_id,
                            prompt_override=prompt_override,
                            require_write=require_write,
                            allow_tool_calls=allow_tool_calls,
                            force_new_conversation=force_new_conversation,
                        )
                except ValueError as exc:
                    yield sse({"error": {"message": str(exc), "type": "invalid_request_error", "code": "invalid_messages"}})
                    yield done_sse()
                    return
                except Exception as exc:
                    yield sse({"error": {"message": str(exc), "type": "server_error", "code": "transport_error"}})
                    yield done_sse()
                    return
                if post_tool_turn and action.kind == "final" and settings.agent_after_tools_plan_enabled:
                    clear_pending_after_tools_plan(resolved_state, dumped_messages)
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
            if post_tool_turn and allow_local_fastpath:
                synthesized = maybe_synthesize_local_final(dumped_messages, pending_after_tools_plan)
                if synthesized is not None:
                    if settings.agent_after_tools_plan_enabled:
                        clear_pending_after_tools_plan(resolved_state, dumped_messages)
                    text, action = synthesized, ParsedAssistantAction(kind="final", content=synthesized)
                else:
                    text, action = resolve_agent_action(
                        model=request.model,
                        dumped_messages=dumped_messages,
                        conversation_id=conversation_id,
                        prompt_override=prompt_override,
                        require_write=require_write,
                        allow_tool_calls=allow_tool_calls,
                        force_new_conversation=force_new_conversation,
                    )
            else:
                text, action = resolve_agent_action(
                    model=request.model,
                    dumped_messages=dumped_messages,
                    conversation_id=conversation_id,
                    prompt_override=prompt_override,
                    require_write=require_write,
                    allow_tool_calls=allow_tool_calls,
                    force_new_conversation=force_new_conversation,
                )
        else:
            text = complete_chat(model=request.model, messages=dumped_messages, conversation_id=conversation_id, prompt_override=prompt_override, force_new_conversation=force_new_conversation)
            action = None
    except ValueError as exc:
        raise openai_error(str(exc), 400, "invalid_messages") from exc

    if agent_mode:
        if post_tool_turn and action.kind == "final" and settings.agent_after_tools_plan_enabled:
            clear_pending_after_tools_plan(resolved_state, dumped_messages)
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
