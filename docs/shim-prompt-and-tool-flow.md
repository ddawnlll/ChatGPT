# Shim Prompt Building and Tool-Call Flow

This document explains how the current proxy shim turns an OpenAI-style chat request into a browser-backed ChatGPT request, how tool calls are encoded and parsed, and where the current latency/token costs come from.

## Relevant files

- `proxy/app/router.py`
- `proxy/app/tools_shim.py`
- `proxy/app/client.py`
- `proxy/app/state.py`
- `tools/playwright_chat_transport.mjs`

## High-level flow

1. Client sends `POST /v1/chat/completions` with OpenAI-style `messages` and optional `tools`.
2. `proxy/app/router.py` decides whether this is a normal chat request or a pi-agent tool request.
3. For pi-agent requests, `proxy/app/tools_shim.py::build_pi_agent_prompt()` builds one large prompt override.
4. The proxy sends that prompt override to the Playwright transport as if it were the user prompt.
5. ChatGPT browser output is normalized in `tools/playwright_chat_transport.mjs`.
6. The normalized assistant text is parsed by `proxy/app/tools_shim.py::parse_assistant_action()`.
7. The proxy returns either:
   - an OpenAI-style `tool_calls` response, or
   - a final assistant message.
8. On later turns, tool results from pi are included in `messages`, and the shim builds a new prompt from the updated transcript.

## Agent-mode detection

File: `proxy/app/tools_shim.py`

The shim treats a request as a pi-agent request if any declared tool name matches:

- `read`
- `write`
- `edit`
- `bash`
- `grep`
- `find`
- `ls`

Function:

- `is_pi_agent_request(tools)`

This means the browser model is not allowed to answer like plain ChatGPT. It is expected to emit tool-call XML or `final_response` XML.

## Prompt building

File: `proxy/app/tools_shim.py`

Main entry point:

- `build_pi_agent_prompt(messages, tools)`

### What goes into the built prompt

The shim builds one synthetic prompt containing:

1. A fixed system-style instruction block
2. A rendered list of available tools
3. A compacted transcript of recent messages
4. Output-format rules
5. Tool-use policy
6. Write-specific rules

### Transcript compaction

The shim does not send the raw OpenAI message array directly to ChatGPT. Instead it renders a compact transcript.

Helpers:

- `_compact_transcript_parts(messages)`
- `_truncate_middle(text, limit)`
- `_stringify_content(content)`

Behavior:

- Keeps the last `MAX_TRANSCRIPT_MESSAGES = 8` messages
- Caps total transcript text at `MAX_TOTAL_TRANSCRIPT_CHARS = 12000`
- Tool results are truncated to `MAX_TOOL_RESULT_CHARS = 3000`
- Assistant tool calls are serialized as JSON-ish text under `assistant_tool_calls:`
- Tool outputs are serialized under `tool_result:`
- Internal repair prompts are filtered out

### Important prompt rules

The synthetic prompt tells ChatGPT:

- it is operating through pi tools
- it must not claim it lacks filesystem access
- repo-analysis tasks must call tools first
- output must be exactly one of:
  - `<tool_call>...</tool_call>`
  - multiple `<tool_call>` blocks for safe batching
  - `<final_response>...</final_response>`

### Current write contract

For `write`, the prompt now requires:

```xml
<tool_call>
<name>write</name>
<arguments>
<path>path/to/file</path>
</arguments>
</tool_call>
<write_content>
```python
RAW FILE CONTENT
```
</write_content>
```

Rules:

- exactly one fenced block inside `<write_content>`
- no content outside the fenced block
- no split across multiple fenced blocks
- correct language fence when known

## Extra router-side prompt forcing

File: `proxy/app/router.py`

After `build_pi_agent_prompt()`, the router may append more instructions.

### Request options

If request fields are set:

- `parallel_tool_calls=true`
- `tool_choice="required"`

then extra hints are appended to the prompt override.

### Write-required classification

Function:

- `request_requires_write_tool(messages, tools)`

If the latest user request looks like a file-creation/write task, the router appends a stronger rule saying the model must emit a write tool call on that turn.

This now only applies before any tool result is present in the current message list, to avoid repeated write loops.

### Tool-access refusal recovery

If the model answers with prose like:

- "I don't have access..."
- "I can't create..."

then the router may do one extra recovery prompt via:

- `build_tool_access_recovery_prompt(...)`

This is intended to recover from false refusals.

## Browser transport normalization

File: `tools/playwright_chat_transport.mjs`

The Playwright transport does not just return raw DOM text. It normalizes assistant output.

Important helpers:

- `extractFinalResponseText()`
- `extractToolCallText()`
- `extractWriteContentText()`
- `extractToolCallWithWriteContent()`
- `normalizeAssistantText()`
- `chooseBetterAssistantText()`

### Important behavior

- For `write`, the transport preserves adjacent `<write_content>` along with the `<tool_call>` block.
- Rendered code blocks are reserialized back into fenced markdown.
- `<pre><code>` extraction now uses `innerText` first so code newlines are preserved.

## Parsing assistant output

File: `proxy/app/tools_shim.py`

Main entry point:

- `parse_assistant_action(text)`

Possible parse results:

- `kind="tool"`
- `kind="tools"`
- `kind="final"`
- `kind="invalid_tool"`

### Tool parsing formats supported

1. XML tool-call format
2. Legacy JSON-inside-`<tool_call>` format
3. Multiple XML tool calls in one message

### Write parsing

For `write`, the parser supports:

- `<write_content>...</write_content>` after the tool call
- legacy JSON `arguments.content`
- XML `<content>...</content>` inside `<arguments>`

### Fenced write-content validation

Helpers:

- `_unwrap_single_markdown_fence(content)`
- `_clean_write_content(path, content, require_fence=...)`
- `_validate_write_arguments(arguments, require_fence=...)`

Behavior for `<write_content>` / XML write payloads:

- requires exactly one fenced block
- rejects multiple fenced blocks
- rejects text outside the outer fence
- unwraps the fence
- normalizes Python dunder markdown artifacts
- validates Python with `ast.parse()` for `.py` files

## Repair behavior

File: `proxy/app/tools_shim.py`

Functions:

- `should_retry_malformed_tool_call(action)`
- `build_tool_repair_prompt(bad_response, parse_error)`

Current behavior:

- some malformed tool-call formats are retried once
- write-specific failures are not retried automatically for syntax/content/path errors
- repair prompts are filtered back out of future transcript compaction

## OpenAI response shaping

File: `proxy/app/router.py`

Function:

- `action_tool_calls(action)`

If parsed action is a tool call, the proxy returns an OpenAI-compatible response with:

- `finish_reason = "tool_calls"`
- `message.tool_calls = [...]`
- serialized `function.arguments`

If parsed action is final text, the proxy returns a normal assistant message.

## Conversation state and continuation

Files:

- `proxy/app/client.py`
- `proxy/app/state.py`

The proxy stores conversation state so follow-up turns continue the same remote ChatGPT thread.

Important pieces:

- `fingerprint_messages(messages)`
- `ConversationStore`
- `RuntimeClient._resolve_state(...)`
- `RuntimeClient._update_state_after_response(...)`

The proxy binds message-history fingerprints to an internal conversation state. That lets follow-up requests reuse the same browser transport and remote conversation identifiers.

## Why one task can currently take two turns

The current design is still classic tool-agent flow:

1. turn 1: model emits tool call
2. pi executes tool
3. turn 2: model sees tool result and emits final response

That is correct for tasks that need observation after execution, but expensive for trivial tasks like:

- write one file, then just acknowledge success
- read one file, then summarize briefly

## Current batching support

The prompt already allows multiple tool calls in one response when safe.

Supported in parser/router:

- multiple XML `<tool_call>` blocks
- OpenAI response can contain multiple tool calls

Intended use:

- independent read-only inspection calls in one turn
- not dependent multi-step workflows

## Main speed bottlenecks

1. Large synthetic prompt every turn
2. Two-turn tool loop for many tasks
3. Browser transport overhead
4. Recovery/repair extra turns when model drifts
5. Full transcript re-rendering on each turn

## Recommended design for a faster mode

If the goal is speed and lower token usage, prefer a strict mode such as:

### Mode A: one tool phase, one final phase max

For each request:

- phase 1: model may emit
  - one final response, or
  - one batch of tool calls
- phase 2: after tool execution, model must emit one final response only
- no further tool calls after tool results unless explicitly enabled

This avoids loops and bounds cost.

### Mode B: direct tool mode for simple requests

For clearly simple tasks:

- allow exactly one tool call
- skip the second model round entirely
- proxy synthesizes a short final acknowledgement from the tool result, or returns tool result directly

Good candidates:

- single `write`
- single `edit`
- single `bash` with explicit command request

Tradeoff:

- faster and cheaper
- but less natural explanation quality unless the proxy generates the final text itself

### Mode C: bounded multi-tool planning

Allow one assistant response containing multiple tool calls, but only for:

- read/ls/find/grep/bash inspection operations

Then after all tool results return:

- exactly one final response
- no second tool-planning pass

This is the best near-term speedup for repo analysis.

## Suggested feature shape

I would design it as an explicit request policy, not implicit magic.

Example knobs:

- `tool_round_limit=1` or `tool_round_limit=2`
- `final_after_tools=true`
- `allow_followup_tool_calls=false`
- `simple_write_fastpath=true`
- `parallel_tool_calls=true`

Recommended default:

- allow one assistant tool-planning response
- allow batched independent read-only tool calls
- after any tool result, require final response only
- for single-file write tasks, consider a fast path that ends after the write succeeds

## Files to inspect next for the speed feature

If we want to implement this carefully, the most important files are:

1. `proxy/app/router.py`
   - request policy
   - round limiting
   - follow-up behavior after tool results
2. `proxy/app/tools_shim.py`
   - prompt policy text
   - parser expectations
3. `proxy/app/client.py`
   - state reuse and transcript aliasing
4. `tests/test_pi_agent_cli_e2e.py`
   - end-to-end loop behavior
5. `tests/test_router_agent_regressions.py`
   - prompt-policy regressions
6. `tools/playwright_chat_transport.mjs`
   - only if transport token cost or partial streaming behavior matters

## Short recommendation

For speed, I would not jump to "multiple answers at the same time."

I would implement:

1. batched independent tool calls in one assistant turn
2. hard limit of one post-tool final response turn
3. optional fast path for simple write/edit tasks

That gives a big latency/token win without making the state machine much more fragile.
