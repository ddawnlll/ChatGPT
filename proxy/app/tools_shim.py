from __future__ import annotations

import ast
import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_TOOL_RESULT_CHARS = 3000
MAX_TRANSCRIPT_MESSAGES = 8
MAX_TOTAL_TRANSCRIPT_CHARS = 12000
REPAIR_PROMPT_PREFIX = "Your previous response was malformed and could not be executed as a tool call."
_INTERNAL_REPAIR_MARKERS = (
    REPAIR_PROMPT_PREFIX,
    "Re-emit the answer as exactly one corrected tool response.",
    "Malformed previous response to repair:",
)

PI_TOOL_NAMES = frozenset({"read", "write", "edit", "bash", "grep", "find", "ls"})


@dataclass(slots=True)
class ShimDecision:
    prompt: str
    tools: list[dict[str, Any]]
    agent_mode: bool


@dataclass(slots=True)
class ParsedToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class ParsedAfterTools:
    on_success: str | None = None
    on_failure: str | None = None
    final_prompt: str | None = None


@dataclass(slots=True)
class ParsedAssistantAction:
    kind: str
    content: str | None = None
    tool_name: str | None = None
    tool_arguments: dict[str, Any] | None = None
    tool_calls: list[ParsedToolCall] | None = None
    after_tools: ParsedAfterTools | None = None
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


def _truncate_middle(text: str, limit: int) -> str:
    text = str(text or "")
    if len(text) <= limit:
        return text
    head = limit // 2
    tail = limit - head
    return text[:head] + f"\n\n...[truncated {len(text) - limit} chars]...\n\n" + text[-tail:]



def _is_internal_repair_text(content: str) -> bool:
    normalized = str(content or "").strip()
    return any(marker in normalized for marker in _INTERNAL_REPAIR_MARKERS)



def _is_internal_repair_prompt(role: str, content: str) -> bool:
    return role == "user" and _is_internal_repair_text(content)



def _safe_tool_arg_int(arguments: dict[str, Any], key: str) -> int | None:
    value = arguments.get(key)
    return value if isinstance(value, int) else None



def _safe_tool_arg_str(arguments: dict[str, Any], key: str) -> str | None:
    value = arguments.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None



def _summarize_single_tool_call(tool_call: dict[str, Any]) -> str:
    function = tool_call.get("function") if isinstance(tool_call, dict) else None
    if not isinstance(function, dict):
        return "- unknown_tool_call"

    name = str(function.get("name") or tool_call.get("name") or "unknown").strip() or "unknown"
    raw_arguments = function.get("arguments")
    arguments: dict[str, Any] = {}
    if isinstance(raw_arguments, str):
        try:
            parsed = json.loads(raw_arguments)
            if isinstance(parsed, dict):
                arguments = parsed
        except Exception:
            arguments = {}
    elif isinstance(raw_arguments, dict):
        arguments = raw_arguments

    if name == "write":
        path = _safe_tool_arg_str(arguments, "path") or _safe_tool_arg_str(arguments, "filename") or "?"
        content = arguments.get("content")
        content_len = len(content) if isinstance(content, str) else 0
        return f"- write {path} content=[omitted {content_len} chars]"
    if name == "edit":
        path = _safe_tool_arg_str(arguments, "path") or "?"
        edits = arguments.get("edits")
        edit_count = len(edits) if isinstance(edits, list) else "?"
        return f"- edit {path} edits={edit_count}"
    if name == "read":
        return f"- read {_safe_tool_arg_str(arguments, 'path') or '?'}"
    if name == "ls":
        return f"- ls {_safe_tool_arg_str(arguments, 'path') or '?'}"
    if name == "find":
        path = _safe_tool_arg_str(arguments, "path") or "?"
        pattern = _safe_tool_arg_str(arguments, "pattern")
        return f'- find {path}{f" pattern=\"{pattern}\"" if pattern else ""}'
    if name == "grep":
        path = _safe_tool_arg_str(arguments, "path") or "?"
        pattern = _safe_tool_arg_str(arguments, "pattern")
        return f'- grep {path}{f" pattern=\"{pattern}\"" if pattern else ""}'
    if name == "bash":
        command = _safe_tool_arg_str(arguments, "command")
        timeout = _safe_tool_arg_int(arguments, "timeout")
        command_preview = _truncate_middle(command, 120) if command else "?"
        return f'- bash "{command_preview}"{f" timeout={timeout}" if timeout is not None else ""}'
    return f"- {name}"



def _summarize_assistant_tool_calls(tool_calls: Any) -> str:
    if not isinstance(tool_calls, list) or not tool_calls:
        return "assistant_tool_calls: - none"
    summaries = [_summarize_single_tool_call(tool_call) for tool_call in tool_calls if isinstance(tool_call, dict)]
    if not summaries:
        summaries = ["- unknown_tool_call"]
    return "assistant_tool_calls:\n" + "\n".join(summaries)



def _compact_transcript_parts(messages: list[dict[str, Any]]) -> list[str]:
    relevant = messages[-MAX_TRANSCRIPT_MESSAGES:]
    parts: list[str] = []
    for message in relevant:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", "")).strip() or "unknown"
        if role in {"system", "developer"}:
            continue
        content = _stringify_content(message.get("content"))
        if _is_internal_repair_prompt(role, content):
            continue
        if role == "assistant" and message.get("tool_calls"):
            parts.append(_summarize_assistant_tool_calls(message.get("tool_calls")))
            continue
        if role == "tool" and content.strip():
            parts.append("tool_result: " + _truncate_middle(content.strip(), MAX_TOOL_RESULT_CHARS))
            continue
        if content.strip():
            parts.append(f"{role}: {_truncate_middle(content.strip(), 2000)}")

    joined = "\n\n".join(parts)
    if len(joined) <= MAX_TOTAL_TRANSCRIPT_CHARS:
        return parts
    return [_truncate_middle(joined, MAX_TOTAL_TRANSCRIPT_CHARS)]



def _build_planning_prompt(*, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> str:
    system_parts: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", "")).strip() or "unknown"
        content = _stringify_content(message.get("content"))
        if role in {"system", "developer"} and content.strip():
            system_parts.append(content.strip())

    transcript_parts = _compact_transcript_parts(messages)
    tool_block = "\n".join(_tool_descriptions(tools)) or "- No tools"
    system_block = "\n\n".join(system_parts).strip()
    transcript = "\n\n".join(transcript_parts).strip()

    prompt = (
        "You are the coding agent operating on the user's local project workspace through pi tools.\n"
        "Treat pi tools as your execution environment and source of truth.\n"
        "You are not operating inside ChatGPT's own environment.\n"
        "Do not say you cannot access the repository just because ChatGPT itself has no filesystem access.\n"
        "Your only way to inspect, modify, or verify the project is by calling tools.\n"
        "The repository exists for you through tool calls, not through built-in ChatGPT knowledge.\n\n"
        "Workspace and repo rules:\n"
        "- If the user asks to analyze, inspect, summarize, debug, search, modify, or understand the repo, you MUST call tools first.\n"
        "- For repo analysis, begin with inspection tools such as ls, find, grep, read, or safe bash commands.\n"
        "- Do not produce <final_response> for repository-analysis tasks until you have inspected the workspace through tools.\n"
        "- Never invent repository structure, file contents, command output, or test results.\n"
        "- Never answer repo questions from assumed knowledge when a tool can verify the answer.\n"
        "- Do not narrate what you would do if a tool can do it now.\n"
        "- Do not answer \"I cannot access the repo\" unless a tool call fails and the tool result proves access is unavailable.\n\n"
        "Tool-use policy:\n"
        "When tools are available, prefer using them instead of writing long prose.\n"
        "You may emit multiple independent tool calls in one response when they can safely run in parallel.\n"
        "Use multiple <tool_call>...</tool_call> blocks for safe batching.\n"
        "Only batch independent read-only or inspection commands, such as ls, find, grep, read, and safe bash commands.\n"
        "Do not batch dependent operations. If a later command depends on an earlier result, emit only the first needed tool call.\n"
        "Do not batch multiple write/edit operations unless they are clearly independent and explicitly requested.\n"
        "If a task requires inspecting files, call read, ls, find, grep, or bash.\n"
        "If a task requires modifying an existing file, call edit.\n"
        "If a task requires creating or replacing a whole file, call write.\n"
        "If a task requires running commands or tests, call bash.\n"
        "If the task is complete and no tool is needed, return a final response.\n\n"
        "Repo-analysis defaults:\n"
        "- If the user says \"analyze the repo\", start with one or more inspection tool calls.\n"
        "- Good first steps include ls for top-level structure, find for important files, grep for entrypoints/TODOs/package names, read for README/config/main source files, and bash for safe inspection commands.\n"
        "- For broad repo inspection, batch independent read-only tool calls when safe.\n\n"
        "Return output in exactly one of these formats:\n"
        "1) Preferred tool call format (examples escaped so they are not mistaken for your answer):\n"
        "&lt;tool_call&gt;\n"
        "&lt;name&gt;read&lt;/name&gt;\n"
        "&lt;arguments&gt;\n"
        "&lt;path&gt;app/main.py&lt;/path&gt;\n"
        "&lt;/arguments&gt;\n"
        "&lt;/tool_call&gt;\n\n"
        "For bash, put the exact shell command inside <command>...</command>. Do not JSON-escape shell commands.\n"
        "For edit, use an edits array. Do not put XML inside a JSON string. Preferred XML pattern:\n"
        "&lt;tool_call&gt;\n"
        "&lt;name&gt;edit&lt;/name&gt;\n"
        "&lt;arguments&gt;\n"
        "&lt;path&gt;app/main.py&lt;/path&gt;\n"
        "&lt;edits&gt;\n"
        "&lt;edit&gt;&lt;oldText&gt;OLD TEXT&lt;/oldText&gt;&lt;newText&gt;NEW TEXT&lt;/newText&gt;&lt;/edit&gt;\n"
        "&lt;/edits&gt;\n"
        "&lt;/arguments&gt;\n"
        "&lt;/tool_call&gt;\n"
        "Legacy JSON example for edit:\n"
        "&lt;tool_call&gt;{\"name\":\"edit\",\"arguments\":{\"path\":\"app/main.py\",\"edits\":[{\"oldText\":\"OLD TEXT\",\"newText\":\"NEW TEXT\"}]}}&lt;/tool_call&gt;\n"
        "For write, always use this exact pattern:\n"
        "&lt;tool_call&gt;\n"
        "&lt;name&gt;write&lt;/name&gt;\n"
        "&lt;arguments&gt;\n"
        "&lt;path&gt;path/to/file&lt;/path&gt;\n"
        "&lt;/arguments&gt;\n"
        "&lt;/tool_call&gt;\n"
        "&lt;write_content&gt;\n"
        "```python\n"
        "RAW FILE CONTENT\n"
        "```\n"
        "&lt;/write_content&gt;\n"
        "Rules for write_content:\n"
        "- Put the entire file content inside exactly one fenced markdown code block.\n"
        "- Do not split the file across multiple code blocks.\n"
        "- Do not put any file content outside the fenced block.\n"
        "- Use the correct language fence when known, for example ```python for .py files.\n"
        "- The content inside the fenced block must be the exact file content.\n"
        "- Do not put file content inside JSON.\n"
        "- Do not put file content inside <content>.\n"
        "For simple arguments like path or timeout, use separate XML tags inside <arguments>.\n\n"
        "2) Legacy compatibility format (allowed but less reliable for string-heavy arguments, example escaped so it is not mistaken for your answer):\n"
        "&lt;tool_call&gt;{\"name\":\"read\",\"arguments\":{\"path\":\"app/main.py\"}}&lt;/tool_call&gt;\n\n"
        "3) Final response:\n"
        "Use final_response XML tags around the final answer, for example:\n"
        "&lt;final_response&gt;Ready.&lt;/final_response&gt;\n\n"
        "When answering, output actual unescaped tags as literal text. Do not put them in markdown fences. Do not HTML-escape them.\n"
        "The examples above are escaped only so they are not mistaken for your answer.\n"
        "Do not include prose outside the tags.\n"
        "Preserve indentation exactly as it should appear in the file.\n"
        "If writing Python, every class/function body must be correctly indented and syntactically valid Python.\n"
        "For Python write_content:\n"
        "- Use 4-space indentation inside the fenced block.\n"
        "- Use exactly one ```python fenced block wrapping the whole file.\n"
        "- Use __name__ and __main__ literally when needed.\n"
        "- Before emitting, mentally verify ast.parse would pass.\n"
        "Do not rewrite code into markdown, bullet points, or prose.\n"
        "Do not emit a final_response immediately after a tool_call for the same task. After tool execution, wait for the next turn.\n"
        "You may emit <after_tools> after tool calls as hidden post-tool metadata.\n"
        "Use <after_tools><on_success>...</on_success></after_tools> only when the final reply can be safely determined from whether the tool succeeds.\n"
        "Use <after_tools><on_failure>...</on_failure></after_tools> for concise failure text, optionally with {error}.\n"
        "For read/grep/find/ls/analysis tasks, prefer <after_tools><final_prompt>...</final_prompt></after_tools> instead of claiming unseen facts.\n"
        "Do not include explanations outside those tags.\n\n"
        f"Available tools:\n{tool_block}\n\n"
        f"System instructions:\n{system_block or '(none)'}\n\n"
        f"Conversation transcript:\n{transcript or '(empty)'}"
    )
    return prompt



def _build_final_only_prompt(*, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None, final_prompt_hint: str | None = None) -> str:
    transcript_parts = _compact_transcript_parts(messages)
    transcript = "\n\n".join(transcript_parts).strip()
    latest_user_text = ""
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        if str(message.get("role", "")).strip() != "user":
            continue
        latest_user_text = _stringify_content(message.get("content")).strip()
        if latest_user_text:
            break

    hint_block = f"\n\nAdditional finalization instruction:\n{final_prompt_hint.strip()}" if isinstance(final_prompt_hint, str) and final_prompt_hint.strip() else ""
    return (
        "You are responding after pi tool execution.\n"
        "Do not call tools on this turn.\n"
        "Do not emit <tool_call>.\n"
        "Return exactly one <final_response>...</final_response> block and nothing else.\n"
        "Use the recent tool-call summaries and tool results below to answer the user's request.\n"
        "Do not include tool schemas, write protocol instructions, or repair text.\n\n"
        f"Latest user request:\n{latest_user_text or '(empty)'}\n\n"
        f"Recent compact context:\n{transcript or '(empty)'}"
        f"{hint_block}"
    )



def build_pi_agent_prompt(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> ShimDecision:
    return ShimDecision(prompt=_build_planning_prompt(messages=messages, tools=tools), tools=tools or [], agent_mode=True)



def build_final_after_tools_prompt(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None, final_prompt_hint: str | None = None) -> ShimDecision:
    return ShimDecision(prompt=_build_final_only_prompt(messages=messages, tools=tools, final_prompt_hint=final_prompt_hint), tools=tools or [], agent_mode=True)


_TOOL_TAG_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL | re.IGNORECASE)
_FINAL_TAG_RE = re.compile(r"<final_response>\s*(.*?)\s*</final_response>", re.DOTALL | re.IGNORECASE)
_WRITE_CONTENT_RE = re.compile(r"<write_content>(.*?)</write_content>", re.DOTALL | re.IGNORECASE)
_AFTER_TOOLS_RE = re.compile(r"<after_tools>\s*(.*?)\s*</after_tools>", re.DOTALL | re.IGNORECASE)
_AFTER_TOOLS_ON_SUCCESS_RE = re.compile(r"<on_success>\s*(.*?)\s*</on_success>", re.DOTALL | re.IGNORECASE)
_AFTER_TOOLS_ON_FAILURE_RE = re.compile(r"<on_failure>\s*(.*?)\s*</on_failure>", re.DOTALL | re.IGNORECASE)
_AFTER_TOOLS_FINAL_PROMPT_RE = re.compile(r"<final_prompt>\s*(.*?)\s*</final_prompt>", re.DOTALL | re.IGNORECASE)
_XML_NAME_RE = re.compile(r"<name>\s*(.*?)\s*</name>", re.DOTALL | re.IGNORECASE)
_XML_ARGUMENTS_RE = re.compile(r"<arguments>\s*(.*?)\s*</arguments>", re.DOTALL | re.IGNORECASE)
_XML_ARG_RE = re.compile(r"<([A-Za-z_][A-Za-z0-9_]*)>\s*(.*?)\s*</\1>", re.DOTALL | re.IGNORECASE)
_EDIT_BLOCK_RE = re.compile(r"<edit>\s*(.*?)\s*</edit>", re.DOTALL | re.IGNORECASE)
_EDIT_OLD_TEXT_RE = re.compile(r"<oldText>\s*(.*?)\s*</oldText>", re.DOTALL | re.IGNORECASE)
_EDIT_NEW_TEXT_RE = re.compile(r"<newText>\s*(.*?)\s*</newText>", re.DOTALL | re.IGNORECASE)
_FINAL_RESPONSE_PLACEHOLDERS = {
    "your final answer here",
    "final answer here",
    "your final response here",
    "final response here",
    "FINAL_TEXT",
    "FINAL_ANSWER",
}


def _decode_loose_string(value: str) -> str:
    text = value.strip()
    try:
        return ast.literal_eval(f'"{text}"')
    except Exception:
        return text.replace(r"\n", "\n").replace(r"\t", "\t").replace(r'\"', '"').replace(r"\\", "\\")


_FENCE_LINE_RE = re.compile(r"^[ \t]*(```|~~~)([A-Za-z0-9_.+-]+)?[ \t]*$")


def _unwrap_single_markdown_fence(content: str) -> tuple[str | None, str | None]:
    text = content.replace("\r\n", "\n").replace("\r", "\n")

    if text.startswith("\n"):
        text = text[1:]

    lines = text.splitlines(keepends=True)

    first = next((i for i, line in enumerate(lines) if line.strip()), None)
    last = next((i for i in range(len(lines) - 1, -1, -1) if lines[i].strip()), None)

    if first is None or last is None:
        return "", None

    fence_lines = [
        i for i, line in enumerate(lines)
        if _FENCE_LINE_RE.match(line.strip())
    ]

    if not fence_lines:
        return None, "write_content must contain exactly one fenced code block"

    if fence_lines != [first, last]:
        return None, "write_content must contain exactly one fenced code block wrapping the entire file content"

    start = _FENCE_LINE_RE.match(lines[first].strip())
    end = _FENCE_LINE_RE.match(lines[last].strip())

    if not start or not end or start.group(1) != end.group(1):
        return None, "write_content fenced code block has mismatched fence markers"

    inner = "".join(lines[first + 1:last])

    if any(_FENCE_LINE_RE.match(line.strip()) for line in inner.splitlines()):
        return None, "write_content contains multiple fenced code blocks; use exactly one block"

    return inner, None


def _normalize_python_dunder_markdown(content: str) -> str:
    return re.sub(r"\*\*([A-Za-z_][A-Za-z0-9_]*)\*\*", r"__\1__", content)


def _clean_write_content(path: str, content: str, *, require_fence: bool) -> tuple[str | None, str | None]:
    cleaned = content.replace("\r\n", "\n").replace("\r", "\n")

    if require_fence:
        fenced, fence_error = _unwrap_single_markdown_fence(cleaned)
        if fence_error is not None:
            return None, fence_error
        cleaned = fenced if fenced is not None else cleaned
    elif cleaned.startswith("\n"):
        cleaned = cleaned[1:]

    if Path(path).suffix == ".py":
        cleaned = _normalize_python_dunder_markdown(cleaned)
    if cleaned and not cleaned.endswith("\n"):
        cleaned += "\n"
    return cleaned, None


def _validate_write_arguments(arguments: dict[str, Any], *, require_fence: bool) -> ParsedAssistantAction | None:
    path = arguments.get("path")
    content = arguments.get("content")
    if not isinstance(path, str):
        return ParsedAssistantAction(kind="invalid_tool", parse_error="write tool call missing path")
    if not isinstance(content, str):
        return ParsedAssistantAction(kind="invalid_tool", parse_error="write tool call missing content")
    cleaned, clean_error = _clean_write_content(path, content, require_fence=require_fence)
    if clean_error is not None:
        return ParsedAssistantAction(kind="invalid_tool", parse_error=clean_error)
    assert cleaned is not None
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



def _validate_edit_arguments(arguments: dict[str, Any]) -> ParsedAssistantAction | None:
    path = arguments.get("path")
    if not isinstance(path, str) or not path.strip():
        return ParsedAssistantAction(kind="invalid_tool", parse_error="edit tool call missing path")

    edits = arguments.get("edits")
    if isinstance(edits, str):
        parsed_edits = _parse_xml_edits(edits)
        if parsed_edits is not None:
            edits = parsed_edits
            arguments["edits"] = edits

    if not isinstance(edits, list):
        return ParsedAssistantAction(kind="invalid_tool", parse_error="edit tool call edits must be an array")
    if not edits:
        return ParsedAssistantAction(kind="invalid_tool", parse_error="edit tool call edits must not be empty")

    normalized: list[dict[str, str]] = []
    for edit in edits:
        if not isinstance(edit, dict):
            return ParsedAssistantAction(kind="invalid_tool", parse_error="edit tool call edits entries must be objects")
        old_text = edit.get("oldText")
        new_text = edit.get("newText")
        if not isinstance(old_text, str) or not isinstance(new_text, str):
            return ParsedAssistantAction(kind="invalid_tool", parse_error="edit tool call each edit must include string oldText and newText")
        normalized.append({"oldText": old_text, "newText": new_text})
    arguments["edits"] = normalized
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
        invalid = _validate_write_arguments(arguments, require_fence=True)
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
    invalid = _validate_write_arguments(arguments, require_fence=False)
    if invalid is not None:
        return invalid
    return ParsedAssistantAction(
        kind="tool",
        tool_name="write",
        tool_arguments=arguments,
    )


def _normalize_xml_text_value(value: str) -> str:
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("\n"):
        text = text[1:]
    if text.endswith("\n"):
        text = text[:-1]
    return text



def _parse_xml_edits(value: str) -> list[dict[str, str]] | None:
    matches = [match.group(1) for match in _EDIT_BLOCK_RE.finditer(value or "")]
    if not matches:
        return None
    edits: list[dict[str, str]] = []
    for body in matches:
        old_match = _EDIT_OLD_TEXT_RE.search(body)
        new_match = _EDIT_NEW_TEXT_RE.search(body)
        if not old_match or not new_match:
            return None
        edits.append(
            {
                "oldText": _normalize_xml_text_value(old_match.group(1)),
                "newText": _normalize_xml_text_value(new_match.group(1)),
            }
        )
    return edits



def _coerce_xml_arg_value(name: str, value: str) -> Any:
    value = value.strip()
    lower_name = name.strip().lower()
    lower_value = value.lower()

    if lower_name == "edits":
        parsed_edits = _parse_xml_edits(value)
        return parsed_edits if parsed_edits is not None else value
    if lower_name in {"timeout", "limit", "max_results"}:
        try:
            return int(value)
        except ValueError:
            return value
    if lower_value == "true":
        return True
    if lower_value == "false":
        return False
    return value



def _parse_xml_tool_payload(payload: str, raw: str) -> ParsedAssistantAction | None:
    name_match = _XML_NAME_RE.search(payload)
    if not name_match:
        return None

    name = name_match.group(1).strip()
    if not name:
        return ParsedAssistantAction(kind="invalid_tool", parse_error="xml tool_call missing name")
    if name == "tool_name":
        return ParsedAssistantAction(kind="invalid_tool", parse_error="placeholder tool name")

    arguments: dict[str, Any] = {}
    arguments_match = _XML_ARGUMENTS_RE.search(payload)
    if arguments_match:
        arguments_body = arguments_match.group(1)
        for match in _XML_ARG_RE.finditer(arguments_body):
            key = match.group(1).strip()
            value = match.group(2)
            arguments[key] = _coerce_xml_arg_value(key, value)

    if name == "write":
        require_fence = isinstance(arguments.get("content"), str)
        if "content" not in arguments:
            write_content_match = _WRITE_CONTENT_RE.search(raw)
            if write_content_match:
                content = write_content_match.group(1)
                if content.startswith("\n"):
                    content = content[1:]
                arguments["content"] = content
                require_fence = True

        if "content" not in arguments:
            content_match = re.search(r"<content>(.*?)</content>", payload, re.DOTALL | re.IGNORECASE)
            if content_match:
                content = content_match.group(1)
                if content.startswith("\n"):
                    content = content[1:]
                arguments["content"] = content
                require_fence = True

        invalid = _validate_write_arguments(arguments, require_fence=require_fence)
        if invalid is not None:
            return invalid
    if name == "edit":
        invalid = _validate_edit_arguments(arguments)
        if invalid is not None:
            return invalid

    return ParsedAssistantAction(kind="tool", tool_name=name, tool_arguments=arguments)



def _parse_tool_payload(payload: str, raw: str) -> ParsedAssistantAction:
    try:
        data = json.loads(payload)
        name = data.get("name")
        arguments = data.get("arguments")
        if isinstance(name, str) and isinstance(arguments, dict):
            if name.strip() == "tool_name":
                return ParsedAssistantAction(kind="invalid_tool", parse_error="placeholder tool name")
            if name == "write":
                path = arguments.get("path")
                require_fence = False
                if isinstance(arguments.get("filename"), str) and not isinstance(path, str):
                    arguments = {**arguments, "path": arguments["filename"]}
                    arguments.pop("filename", None)
                content_match = _WRITE_CONTENT_RE.search(raw)
                if content_match:
                    content = content_match.group(1)
                    if content.startswith("\n"):
                        content = content[1:]
                    arguments = {**arguments, "content": content}
                    require_fence = True
                invalid = _validate_write_arguments(arguments, require_fence=require_fence)
                if invalid is not None:
                    return invalid
            if name == "edit":
                invalid = _validate_edit_arguments(arguments)
                if invalid is not None:
                    return invalid
            return ParsedAssistantAction(kind="tool", tool_name=name, tool_arguments=arguments)
    except Exception as exc:
        recovered = _recover_write_payload(payload, raw)
        if recovered is not None:
            return recovered
        return ParsedAssistantAction(kind="invalid_tool", parse_error=str(exc))
    return ParsedAssistantAction(kind="invalid_tool", parse_error="tool payload missing name/arguments")


def _extract_tool_call(raw: str) -> ParsedAssistantAction | None:
    matches = [match.group(1).strip() for match in _TOOL_TAG_RE.finditer(raw or "")]
    first_invalid: ParsedAssistantAction | None = None
    calls: list[ParsedToolCall] = []

    for payload in matches:
        xml_parsed = _parse_xml_tool_payload(payload, raw)
        parsed = xml_parsed if xml_parsed is not None else _parse_tool_payload(payload, raw)
        if parsed.kind == "tool" and parsed.tool_name and isinstance(parsed.tool_arguments, dict):
            calls.append(ParsedToolCall(name=parsed.tool_name, arguments=parsed.tool_arguments))
            continue
        if first_invalid is None:
            first_invalid = parsed

    if len(calls) == 1:
        return ParsedAssistantAction(kind="tool", tool_name=calls[0].name, tool_arguments=calls[0].arguments, tool_calls=calls)
    if len(calls) > 1:
        return ParsedAssistantAction(kind="tools", tool_calls=calls)
    return first_invalid



def _extract_after_tools(raw: str) -> ParsedAfterTools | None:
    matches = [match.group(1).strip() for match in _AFTER_TOOLS_RE.finditer(raw or "")]
    if not matches:
        return None
    body = matches[-1]
    on_success = _AFTER_TOOLS_ON_SUCCESS_RE.search(body)
    on_failure = _AFTER_TOOLS_ON_FAILURE_RE.search(body)
    final_prompt = _AFTER_TOOLS_FINAL_PROMPT_RE.search(body)
    parsed = ParsedAfterTools(
        on_success=on_success.group(1).strip() if on_success and on_success.group(1).strip() else None,
        on_failure=on_failure.group(1).strip() if on_failure and on_failure.group(1).strip() else None,
        final_prompt=final_prompt.group(1).strip() if final_prompt and final_prompt.group(1).strip() else None,
    )
    if parsed.on_success or parsed.on_failure or parsed.final_prompt:
        return parsed
    return None



def _extract_final_response(raw: str) -> str | None:
    matches = [match.group(1).strip() for match in _FINAL_TAG_RE.finditer(raw or "")]

    for value in reversed(matches):
        normalized = re.sub(r"\s+", " ", value).strip()
        if normalized and normalized not in _FINAL_RESPONSE_PLACEHOLDERS:
            return value

    return None



def _detect_incomplete_tagged_response(raw: str) -> str | None:
    stripped = str(raw or "").strip()
    lowered = stripped.lower()
    if stripped in {"<", "</", "<tool", "<tool_", "<tool_c", "<tool_ca", "<tool_cal", "<tool_call", "<name", "<arguments", "<command", "<content"}:
        return "incomplete tagged response"
    if stripped in {"<final", "<final_", "<final_r", "<final_re", "<final_res", "<final_resp", "<final_respo", "<final_respon", "<final_response"}:
        return "incomplete final_response tag"
    if "<tool_call" in lowered and not _TOOL_TAG_RE.search(stripped):
        return "incomplete tool_call tag"
    if "<final" in lowered and not _FINAL_TAG_RE.search(stripped):
        return "incomplete final_response tag"
    if "<write_content" in lowered and not _WRITE_CONTENT_RE.search(stripped):
        return "incomplete write_content tag"
    return None



def parse_assistant_action(text: str) -> ParsedAssistantAction:
    raw = str(text or "").strip()
    tool_action = _extract_tool_call(raw)
    final_response = _extract_final_response(raw)
    after_tools = _extract_after_tools(raw)

    if tool_action is not None:
        if tool_action.kind == "tool":
            if after_tools is not None:
                return ParsedAssistantAction(kind="tool_plan", tool_name=tool_action.tool_name, tool_arguments=tool_action.tool_arguments, tool_calls=tool_action.tool_calls, after_tools=after_tools)
            return tool_action
        if tool_action.kind == "tools":
            if after_tools is not None:
                return ParsedAssistantAction(kind="tools_plan", tool_calls=tool_action.tool_calls, after_tools=after_tools)
            return tool_action
        if final_response is None:
            return tool_action

    if final_response is not None:
        return ParsedAssistantAction(kind="final", content=final_response)

    incomplete_error = _detect_incomplete_tagged_response(raw)
    if incomplete_error:
        return ParsedAssistantAction(kind="invalid_tool", parse_error=incomplete_error)

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
    if any(
        token in error
        for token in (
            "write tool call missing content",
            "write tool call missing path",
            "python write content failed syntax validation",
        )
    ):
        return False
    if not error:
        return True
    return any(
        token in error
        for token in (
            "syntax validation",
            "expecting",
            "delimiter",
            "json",
            "incomplete tagged response",
            "incomplete tool_call tag",
            "incomplete write_content tag",
            "tool payload missing",
        )
    )


def build_tool_repair_prompt(bad_response: str, parse_error: str | None) -> str:
    detail = parse_error or "unknown malformed tool call"
    return (
        f"{REPAIR_PROMPT_PREFIX}\n"
        f"Validation error: {detail}\n\n"
        "Re-emit the answer as exactly one corrected tool response.\n"
        "If the intended tool is write, use this exact safer format:\n"
        "<tool_call>\n"
        "<name>write</name>\n"
        "<arguments>\n"
        "<path>path/to/file</path>\n"
        "</arguments>\n"
        "</tool_call>\n"
        "<write_content>\n```python\nRAW FILE CONTENT HERE\n```\n</write_content>\n\n"
        "Rules:\n"
        "- Output the entire file only inside <write_content>.\n"
        "- Wrap the entire file in exactly one fenced markdown code block.\n"
        "- Do not split the file across multiple code blocks.\n"
        "- Do not put any file content outside the fenced block.\n"
        "- Do not put write file content inside JSON.\n"
        "- Do not put write file content inside <content>.\n"
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
