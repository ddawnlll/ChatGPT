from __future__ import annotations

import ast
import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PI_TOOL_NAMES = frozenset({"read", "write", "edit", "bash", "grep", "find", "ls"})


@dataclass(slots=True)
class ShimDecision:
    prompt: str
    tools: list[dict[str, Any]]
    agent_mode: bool


@dataclass(slots=True)
class ParsedAssistantAction:
    kind: str
    content: str | None = None
    tool_name: str | None = None
    tool_arguments: dict[str, Any] | None = None
    parse_error: str | None = None


def _tool_name_set(tools: list[dict[str, Any]] | None) -> set[str]:
    names: set[str] = set()
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function", {})
        if isinstance(function, dict):
            name = function.get("name") or tool.get("name")
        else:
            name = tool.get("name")
        if isinstance(name, str) and name.strip():
            names.add(name.strip())
    return names


def is_pi_agent_request(tools: list[dict[str, Any]] | None) -> bool:
    names = _tool_name_set(tools)
    return bool(names & PI_TOOL_NAMES)


def _stringify_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part for part in parts if part)
    return str(content)


def _tool_descriptions(tools: list[dict[str, Any]] | None) -> list[str]:
    rows: list[str] = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function", {})
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if not isinstance(name, str) or not name:
            continue
        description = function.get("description") if isinstance(function.get("description"), str) else ""
        parameters = function.get("parameters")
        param_preview = ""
        if parameters is not None:
            try:
                param_preview = json.dumps(parameters, ensure_ascii=False)
            except Exception:
                param_preview = str(parameters)
        rows.append(f"- {name}: {description or 'No description'}{f' | parameters={param_preview}' if param_preview else ''}")
    return rows


def build_pi_agent_prompt(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> ShimDecision:
    system_parts: list[str] = []
    transcript_parts: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", "")).strip() or "unknown"
        content = _stringify_content(message.get("content"))
        if role in {"system", "developer"} and content.strip():
            system_parts.append(content.strip())
        if role == "assistant" and message.get("tool_calls"):
            transcript_parts.append(f"assistant_tool_calls: {json.dumps(message.get('tool_calls'), ensure_ascii=False)}")
            continue
        if role == "tool" and content.strip():
            transcript_parts.append(f"tool_result: {content.strip()}")
            continue
        if content.strip():
            transcript_parts.append(f"{role}: {content.strip()}")

    tool_block = "\n".join(_tool_descriptions(tools)) or "- No tools"
    system_block = "\n\n".join(system_parts).strip()
    transcript = "\n\n".join(transcript_parts).strip()

    prompt = (
        "You are operating as a coding agent for pi.\n"
        "You must behave like a tool-using coding assistant, not a normal chat bot.\n"
        "When tools are available, prefer using them instead of writing long prose.\n"
        "Use at most one tool call at a time.\n"
        "If a task requires inspecting files, call read.\n"
        "If a task requires modifying an existing file, call edit.\n"
        "If a task requires creating or replacing a whole file, call write.\n"
        "If a task requires running commands or tests, call bash.\n"
        "If the task is complete and no tool is needed, return a final response.\n\n"
        "Return output in exactly one of these formats:\n"
        "1) Standard tools:\n"
        "<tool_call>{\"name\":\"tool_name\",\"arguments\":{...}}</tool_call>\n\n"
        "2) Safer write format for large file content or code with quotes/triple quotes:\n"
        "<tool_call>{\"name\":\"write\",\"arguments\":{\"path\":\"path/to/file\"}}</tool_call>\n"
        "<write_content>\nRAW FILE CONTENT HERE\n</write_content>\n\n"
        "3) Final response:\n"
        "<final_response>your final answer here</final_response>\n\n"
        "For write, prefer the safer write_content format instead of JSON-escaping the whole file body.\n"
        "Inside <write_content>, output raw file contents only. Do not add markdown fences like ``` or ```python.\n"
        "Preserve indentation exactly as it should appear in the file.\n"
        "If writing Python, every class/function body must be correctly indented and syntactically valid Python.\n"
        "Do not rewrite code into markdown, bullet points, or prose.\n"
        "Do not emit a final_response immediately after a tool_call for the same task. After tool execution, wait for the next turn.\n"
        "Do not include explanations outside those tags.\n\n"
        f"Available tools:\n{tool_block}\n\n"
        f"System instructions:\n{system_block or '(none)'}\n\n"
        f"Conversation transcript:\n{transcript or '(empty)'}"
    )
    return ShimDecision(prompt=prompt, tools=tools or [], agent_mode=True)


_TOOL_TAG_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL | re.IGNORECASE)
_FINAL_TAG_RE = re.compile(r"<final_response>\s*(.*?)\s*</final_response>", re.DOTALL | re.IGNORECASE)
_WRITE_CONTENT_RE = re.compile(r"<write_content>(.*?)</write_content>", re.DOTALL | re.IGNORECASE)


def _decode_loose_string(value: str) -> str:
    text = value.strip()
    try:
        return ast.literal_eval(f'"{text}"')
    except Exception:
        return text.replace(r"\n", "\n").replace(r"\t", "\t").replace(r'\"', '"').replace(r"\\", "\\")


def _strip_markdown_fences(content: str) -> str:
    lines = content.splitlines()
    cleaned = [line for line in lines if not line.strip().startswith("```")]
    return "\n".join(cleaned)


def _normalize_python_dunder_markdown(content: str) -> str:
    return re.sub(r"\*\*([A-Za-z_][A-Za-z0-9_]*)\*\*", r"__\1__", content)


def _clean_write_content(path: str, content: str) -> str:
    cleaned = content.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _strip_markdown_fences(cleaned)
    if Path(path).suffix == ".py":
        cleaned = _normalize_python_dunder_markdown(cleaned)
    if cleaned and not cleaned.endswith("\n"):
        cleaned += "\n"
    return cleaned


def _validate_write_arguments(arguments: dict[str, Any]) -> ParsedAssistantAction | None:
    path = arguments.get("path")
    content = arguments.get("content")
    if not isinstance(path, str):
        return ParsedAssistantAction(kind="invalid_tool", parse_error="write tool call missing path")
    if not isinstance(content, str):
        return ParsedAssistantAction(kind="invalid_tool", parse_error="write tool call missing content")
    cleaned = _clean_write_content(path, content)
    if Path(path).suffix == ".py":
        try:
            ast.parse(cleaned)
        except SyntaxError as exc:
            return ParsedAssistantAction(
                kind="invalid_tool",
                parse_error=f"python write content failed syntax validation at line {exc.lineno}: {exc.msg}",
            )
    arguments["content"] = cleaned
    return None


def _recover_write_payload(payload: str, full_text: str) -> ParsedAssistantAction | None:
    name_match = re.search(r'"name"\s*:\s*"([^"]+)"', payload)
    if not name_match or name_match.group(1) != "write":
        return None

    path_match = re.search(r'"path"\s*:\s*"((?:\\.|[^"\\])*)"', payload)
    if not path_match:
        return ParsedAssistantAction(kind="invalid_tool", parse_error="write tool call missing path")

    content_match = _WRITE_CONTENT_RE.search(full_text)
    if content_match:
        content = content_match.group(1)
        if content.startswith("\n"):
            content = content[1:]
        arguments = {"path": _decode_loose_string(path_match.group(1)), "content": content}
        invalid = _validate_write_arguments(arguments)
        if invalid is not None:
            return invalid
        return ParsedAssistantAction(
            kind="tool",
            tool_name="write",
            tool_arguments=arguments,
        )

    marker_match = re.search(r'"content"\s*:\s*"', payload)
    if not marker_match:
        return ParsedAssistantAction(kind="invalid_tool", parse_error="write tool call missing content")

    start = marker_match.end()
    remainder = payload[start:]
    tail_candidates = ['"}}', '" } }', '"}}}', '"}}\n']
    end_positions = [remainder.rfind(candidate) for candidate in tail_candidates if remainder.rfind(candidate) != -1]
    if not end_positions:
        closing_brace = remainder.rfind('"}')
        if closing_brace != -1:
            end_positions.append(closing_brace)
    if not end_positions:
        return ParsedAssistantAction(kind="invalid_tool", parse_error="unable to recover write content")

    end = max(end_positions)
    content = remainder[:end]
    arguments = {"path": _decode_loose_string(path_match.group(1)), "content": _decode_loose_string(content)}
    invalid = _validate_write_arguments(arguments)
    if invalid is not None:
        return invalid
    return ParsedAssistantAction(
        kind="tool",
        tool_name="write",
        tool_arguments=arguments,
    )


def _parse_tool_payload(payload: str, raw: str) -> ParsedAssistantAction:
    try:
        data = json.loads(payload)
        name = data.get("name")
        arguments = data.get("arguments")
        if isinstance(name, str) and isinstance(arguments, dict):
            if name == "write":
                path = arguments.get("path")
                if isinstance(arguments.get("filename"), str) and not isinstance(path, str):
                    arguments = {**arguments, "path": arguments["filename"]}
                    arguments.pop("filename", None)
                content_match = _WRITE_CONTENT_RE.search(raw)
                if content_match:
                    content = content_match.group(1)
                    if content.startswith("\n"):
                        content = content[1:]
                    arguments = {**arguments, "content": content}
                invalid = _validate_write_arguments(arguments)
                if invalid is not None:
                    return invalid
            return ParsedAssistantAction(kind="tool", tool_name=name, tool_arguments=arguments)
    except Exception as exc:
        recovered = _recover_write_payload(payload, raw)
        if recovered is not None:
            return recovered
        return ParsedAssistantAction(kind="invalid_tool", parse_error=str(exc))
    return ParsedAssistantAction(kind="invalid_tool", parse_error="tool payload missing name/arguments")


def parse_assistant_action(text: str) -> ParsedAssistantAction:
    raw = str(text or "").strip()
    tool_match = _TOOL_TAG_RE.search(raw)
    if tool_match:
        return _parse_tool_payload(tool_match.group(1).strip(), raw)

    final_match = _FINAL_TAG_RE.search(raw)
    if final_match:
        return ParsedAssistantAction(kind="final", content=final_match.group(1).strip())

    if raw.startswith("{") and raw.endswith("}"):
        parsed = _parse_tool_payload(raw, raw)
        if parsed.kind in {"tool", "invalid_tool"}:
            return parsed

    write_content_match = _WRITE_CONTENT_RE.search(raw)
    if write_content_match:
        return ParsedAssistantAction(kind="invalid_tool", parse_error="write_content present without preceding write tool_call")

    return ParsedAssistantAction(kind="final", content=raw)


def should_retry_malformed_tool_call(action: ParsedAssistantAction) -> bool:
    if action.kind != "invalid_tool":
        return False
    error = (action.parse_error or "").lower()
    return "write" in error or "python write content failed syntax validation" in error or "syntax validation" in error


def build_tool_repair_prompt(bad_response: str, parse_error: str | None) -> str:
    detail = parse_error or "unknown malformed tool call"
    return (
        "Your previous response was malformed and could not be executed as a tool call.\n"
        f"Validation error: {detail}\n\n"
        "Re-emit the answer as exactly one corrected tool response.\n"
        "If the intended tool is write, use this safer format:\n"
        "<tool_call>{\"name\":\"write\",\"arguments\":{\"path\":\"path/to/file\"}}</tool_call>\n"
        "<write_content>\nRAW FILE CONTENT HERE\n</write_content>\n\n"
        "Rules:\n"
        "- Output raw file contents only inside <write_content>.\n"
        "- No markdown fences.\n"
        "- Preserve indentation exactly.\n"
        "- If Python, ensure syntactically valid indentation and valid __name__ == \"__main__\" style dunder usage.\n"
        "- Do not include <final_response>.\n"
        "- Do not add commentary or explanations.\n\n"
        "Malformed previous response to repair:\n"
        f"{bad_response}"
    )


def build_openai_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"call_{uuid.uuid4().hex[:24]}",
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments, ensure_ascii=False),
        },
    }
