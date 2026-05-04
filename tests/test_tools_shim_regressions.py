from proxy.app.tools_shim import build_final_after_tools_prompt, build_pi_agent_prompt, build_task_continuation_prompt, build_tool_repair_prompt, count_tool_rounds, is_implementation_task, parse_assistant_action, should_retry_malformed_tool_call


def test_parse_final_response_prefers_last_non_placeholder():
    text = """
Return output in exactly one of these formats:

<final_response>your final answer here</final_response>

Actual model output:
<final_response>Ready.</final_response>
"""

    action = parse_assistant_action(text)

    assert action.kind == "final"
    assert action.content == "Ready."


def test_parse_final_response_ignores_placeholder_when_real_answer_exists():
    text = """
<final_response>your final answer here</final_response>
Some page text
<final_response>Done.</final_response>
"""

    action = parse_assistant_action(text)

    assert action.kind == "final"
    assert action.content == "Done."


def test_parse_tool_call_prefers_last_valid_tool_call_over_prompt_example():
    text = """
Example:
<tool_call>{"name":"tool_name","arguments":{}}</tool_call>

Actual:
<tool_call>{"name":"read","arguments":{"path":"server.py"}}</tool_call>
"""

    action = parse_assistant_action(text)

    assert action.kind == "tool"
    assert action.tool_name == "read"
    assert action.tool_arguments == {"path": "server.py"}


def test_parse_final_response_wins_over_placeholder_tool_example():
    text = """
Example:
<tool_call>{"name":"tool_name","arguments":{}}</tool_call>

Actual:
<final_response>Hello.</final_response>
"""

    action = parse_assistant_action(text)

    assert action.kind == "final"
    assert action.content == "Hello."


def test_parse_plain_final_fallback():
    action = parse_assistant_action("Ready.")

    assert action.kind == "final"
    assert action.content == "Ready."


def test_parse_placeholder_tool_call_is_invalid_not_final():
    action = parse_assistant_action("<tool_call>...</tool_call>")

    assert action.kind == "invalid_tool"


def test_parse_incomplete_final_response_tag_is_rejected():
    action = parse_assistant_action("<final")

    assert action.kind == "invalid_tool"
    assert action.parse_error == "incomplete final_response tag"


def test_parse_single_angle_bracket_is_rejected():
    action = parse_assistant_action("<")

    assert action.kind == "invalid_tool"
    assert action.parse_error == "incomplete tagged response"


def test_parse_xml_bash_tool_call_with_raw_command():
    text = r"""
<tool_call>
<name>bash</name>
<arguments>
<timeout>10</timeout>
<command>
find app -print | sed 's|[^/]*/|  |g; s|  \([^ ]\)|├── \1|'
</command>
</arguments>
</tool_call>
"""

    action = parse_assistant_action(text)

    assert action.kind == "tool"
    assert action.tool_name == "bash"
    assert action.tool_arguments == {
        "timeout": 10,
        "command": "find app -print | sed 's|[^/]*/|  |g; s|  \\([^ ]\\)|├── \\1|'\n",
    }



def test_parse_xml_bash_tool_call_with_command_content_sidecar():
    text = """
<tool_call>
<name>bash</name>
<arguments>
<timeout>10</timeout>
</arguments>
</tool_call>
<command_content>
```bash
python - <<'PY'
if True:
    print("ok")
PY
```
</command_content>
"""

    action = parse_assistant_action(text)

    assert action.kind == "tool"
    assert action.tool_name == "bash"
    assert action.tool_arguments == {
        "timeout": 10,
        "command": "python - <<'PY'\nif True:\n    print(\"ok\")\nPY\n",
    }


def test_parse_xml_write_tool_call_with_fenced_content_argument():
    text = """
<tool_call>
<name>write</name>
<arguments>
<path>app/test.py</path>
<content>
```python
print(\"hello world\")
```
</content>
</arguments>
</tool_call>
"""

    action = parse_assistant_action(text)

    assert action.kind == "tool"
    assert action.tool_name == "write"
    assert action.tool_arguments == {
        "path": "app/test.py",
        "content": 'print("hello world")\n',
    }


def test_parse_xml_write_tool_call_with_separate_fenced_write_content_block():
    text = """
<tool_call>
<name>write</name>
<arguments>
<path>server.py</path>
</arguments>
</tool_call>
<write_content>
```python
from http.server import BaseHTTPRequestHandler, HTTPServer

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Hello from server.py\\n")

if __name__ == "__main__":
    pass
```
</write_content>
"""

    action = parse_assistant_action(text)

    assert action.kind == "tool"
    assert action.tool_name == "write"
    assert action.tool_arguments is not None
    assert action.tool_arguments["path"] == "server.py"
    assert 'self.wfile.write(b"Hello from server.py\\n")' in action.tool_arguments["content"]



def test_parse_json_edit_tool_call_with_xml_edits_string_is_normalized():
    text = """
<tool_call>{"name":"edit","arguments":{"path":"app/server4.py","edits":"<edit><oldText>PORT = 8000</oldText><newText>PORT = 8090</newText></edit>"}}</tool_call>
"""

    action = parse_assistant_action(text)

    assert action.kind == "tool"
    assert action.tool_name == "edit"
    assert action.tool_arguments == {
        "path": "app/server4.py",
        "edits": [{"oldText": "PORT = 8000", "newText": "PORT = 8090"}],
    }



def test_parse_xml_edit_tool_call_with_nested_edit_blocks():
    text = """
<tool_call>
<name>edit</name>
<arguments>
<path>app/server4.py</path>
<edits>
<edit>
<oldText>PORT = 8000</oldText>
<newText>PORT = 8090</newText>
</edit>
</edits>
</arguments>
</tool_call>
"""

    action = parse_assistant_action(text)

    assert action.kind == "tool"
    assert action.tool_name == "edit"
    assert action.tool_arguments == {
        "path": "app/server4.py",
        "edits": [{"oldText": "PORT = 8000", "newText": "PORT = 8090"}],
    }


def test_parse_xml_write_rejects_multiple_fenced_blocks():
    text = """
<tool_call>
<name>write</name>
<arguments>
<path>app/server.py</path>
</arguments>
</tool_call>
<write_content>
```python
body = b"hello"
```

def run():
server = None

```python
server.serve_forever()
```
</write_content>
"""

    action = parse_assistant_action(text)

    assert action.kind == "invalid_tool"
    assert action.parse_error is not None
    assert "exactly one fenced code block" in action.parse_error


def test_parse_xml_write_rejects_unindented_fenced_python_write_content():
    text = """
<tool_call>
<name>write</name>
<arguments>
<path>app/server.py</path>
</arguments>
</tool_call>
<write_content>
```python
from http.server import BaseHTTPRequestHandler, HTTPServer

class SimpleHandler(BaseHTTPRequestHandler):
def do_GET(self):
self.send_response(200)
```
</write_content>
"""

    action = parse_assistant_action(text)

    assert action.kind == "invalid_tool"
    assert action.parse_error is not None
    assert "python write content failed syntax validation" in action.parse_error



def test_parse_tool_plan_with_on_success():
    text = """
<tool_call>
<name>write</name>
<arguments>
<path>server.py</path>
</arguments>
</tool_call>
<write_content>
```python
print("hello")
```
</write_content>
<after_tools>
<on_success>Created server.py.</on_success>
<on_failure>Could not create server.py: {error}</on_failure>
</after_tools>
"""

    action = parse_assistant_action(text)

    assert action.kind == "tool_plan"
    assert action.after_tools is not None
    assert action.after_tools.on_success == "Created server.py."
    assert action.after_tools.on_failure == "Could not create server.py: {error}"



def test_parse_multi_tool_plan_with_final_prompt():
    text = """
<tool_call><name>find</name><arguments><path>.</path><pattern>*.py</pattern></arguments></tool_call>
<tool_call><name>grep</name><arguments><path>.</path><pattern>TODO</pattern></arguments></tool_call>
<after_tools>
<final_prompt>Use the tool results to summarize the project in 5 bullets.</final_prompt>
</after_tools>
"""

    action = parse_assistant_action(text)

    assert action.kind == "tools_plan"
    assert action.tool_calls is not None
    assert [call.name for call in action.tool_calls] == ["find", "grep"]
    assert action.after_tools is not None
    assert action.after_tools.final_prompt == "Use the tool results to summarize the project in 5 bullets."



def test_parse_multiple_xml_tool_calls_returns_tools_kind():
    text = """
<tool_call><name>find</name><arguments><path>.</path><pattern>*.py</pattern></arguments></tool_call>
<tool_call><name>grep</name><arguments><path>.</path><pattern>TODO</pattern></arguments></tool_call>
"""

    action = parse_assistant_action(text)

    assert action.kind == "tools"
    assert action.tool_calls is not None
    assert [call.name for call in action.tool_calls] == ["find", "grep"]


def test_task_classifier_recognizes_supported_implementation_template():
    assert is_implementation_task([
        {"role": "user", "content": "You are the implementation agent. Continue and complete this continuation task, not a greenfield build. Inspect the current repository before coding, add tests, run the required test commands, preserve valid existing work, and report files changed and tests run."}
    ]) is True



def test_task_classifier_does_not_classify_simple_prompts():
    assert is_implementation_task([{"role": "user", "content": "hello"}]) is False
    assert is_implementation_task([{"role": "user", "content": "run pwd"}]) is False



def test_task_continuation_prompt_allows_tools_and_includes_round_count():
    decision = build_task_continuation_prompt(
        [
            {"role": "user", "content": "Continue and complete the implementation task. Add tests and run the required test commands."},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "call_bash", "type": "function", "function": {"name": "bash", "arguments": '{"command":"find . -maxdepth 2 -type f | sort"}'}}]},
            {"role": "tool", "tool_call_id": "call_bash", "content": "./app/server4.py"},
        ],
        [{"type": "function", "function": {"name": "read", "description": "Read file", "parameters": {}}}],
        tool_round_count=1,
        max_tool_rounds=12,
    )

    prompt = decision.prompt
    assert "More tool calls are allowed on this turn." in prompt
    assert "Continue the implementation task" in prompt
    assert "Only emit <final_response> when the requested deliverables are complete or you are blocked" in prompt
    assert "Current tool round count: 1" in prompt
    assert "Maximum tool round count: 12" in prompt
    assert "For write, always use this exact pattern" not in prompt
    assert "Malformed previous response to repair:" not in prompt



def test_count_tool_rounds_counts_assistant_tool_turns():
    assert count_tool_rounds([
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "1", "type": "function", "function": {"name": "bash", "arguments": '{}'}}]},
        {"role": "tool", "tool_call_id": "1", "content": "ok"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "2", "type": "function", "function": {"name": "read", "arguments": '{}'}}]},
    ]) == 2



def test_build_pi_agent_prompt_compacts_large_history():
    huge = "x" * 10000
    decision = build_pi_agent_prompt(
        [
            {"role": "user", "content": "first"},
            {"role": "tool", "content": huge},
            {"role": "user", "content": "latest request"},
        ],
        None,
    )

    assert "latest request" in decision.prompt
    assert "[truncated" in decision.prompt
    assert len(decision.prompt) < 20000



def test_compact_transcript_skips_system_and_developer_messages():
    decision = build_pi_agent_prompt(
        [
            {"role": "system", "content": "system alpha"},
            {"role": "developer", "content": "developer beta"},
            {"role": "user", "content": "latest request"},
        ],
        None,
    )

    prompt = decision.prompt
    assert "System instructions:\nsystem alpha\n\ndeveloper beta" in prompt
    transcript = prompt.split("Conversation transcript:\n", 1)[1]
    assert "system: system alpha" not in transcript
    assert "developer: developer beta" not in transcript



def test_compact_transcript_summarizes_assistant_tool_calls_and_omits_write_content():
    decision = build_pi_agent_prompt(
        [
            {"role": "user", "content": "make files"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_write",
                        "type": "function",
                        "function": {
                            "name": "write",
                            "arguments": '{"path":"app/server.py","content":"print(\\"x\\")\\n"}',
                        },
                    },
                    {
                        "id": "call_edit",
                        "type": "function",
                        "function": {
                            "name": "edit",
                            "arguments": '{"path":"app/main.py","edits":[{"oldText":"a","newText":"b"},{"oldText":"c","newText":"d"}]}',
                        },
                    },
                    {
                        "id": "call_bash",
                        "type": "function",
                        "function": {
                            "name": "bash",
                            "arguments": '{"command":"pytest -q","timeout":30}',
                        },
                    },
                    {
                        "id": "call_read",
                        "type": "function",
                        "function": {
                            "name": "read",
                            "arguments": '{"path":"README.md"}',
                        },
                    },
                ],
            },
        ],
        None,
    )

    prompt = decision.prompt
    assert "assistant_tool_calls:" in prompt
    assert "- write app/server.py content=[omitted" in prompt
    assert "print(\"x\")" not in prompt
    assert "- edit app/main.py edits=2" in prompt
    assert '- bash "pytest -q" timeout=30' in prompt
    assert "- read README.md" in prompt



def test_final_only_prompt_contains_no_tool_schema_or_write_protocol():
    decision = build_final_after_tools_prompt(
        [
            {"role": "user", "content": "Summarize README.md"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_read",
                        "type": "function",
                        "function": {"name": "read", "arguments": '{"path":"README.md"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_read", "content": "README contents"},
        ],
        [{"type": "function", "function": {"name": "read", "description": "Read file", "parameters": {}}}],
    )

    prompt = decision.prompt
    assert "Do not call tools on this turn." in prompt
    assert "Return exactly one <final_response>...</final_response> block" in prompt
    assert "Available tools:" not in prompt
    assert "For write, always use this exact pattern" not in prompt
    assert "<write_content>" not in prompt


def test_repo_analysis_prompt_forces_tool_inspection():
    decision = build_pi_agent_prompt(
        [{"role": "user", "content": "analyze the repo"}],
        [
            {"type": "function", "function": {"name": "bash", "description": "Run shell", "parameters": {}}},
            {"type": "function", "function": {"name": "ls", "description": "List files", "parameters": {}}},
        ],
    )

    prompt = decision.prompt.lower()

    assert "you are not operating inside chatgpt" in prompt
    assert "must call tools first" in prompt
    assert 'do not answer "i cannot access the repo"' in prompt
    assert "analyze the repo" in prompt
    assert "ls" in prompt
    assert "bash" in prompt


def test_prompt_prefers_write_content_block_and_skips_internal_repair_prompt():
    decision = build_pi_agent_prompt(
        [
            {"role": "user", "content": "Create server.py"},
            {"role": "user", "content": build_tool_repair_prompt("bad", "write tool call missing content")},
        ],
        [{"type": "function", "function": {"name": "write", "description": "Write file", "parameters": {}}}],
    )

    prompt = decision.prompt
    assert "&lt;write_content&gt;" in prompt
    assert "Do not put file content inside JSON." in prompt
    assert "Do not put file content inside <content>." in prompt
    assert "exactly one fenced markdown code block" in prompt
    assert "```python" in prompt
    assert "Create server.py" in prompt
    assert "Your previous response was malformed and could not be executed as a tool call." not in prompt
    assert "Malformed previous response to repair:" not in prompt


def test_write_missing_content_is_not_retryable():
    action = parse_assistant_action(
        """
<tool_call>
<name>write</name>
<arguments>
<path>server.py</path>
</arguments>
</tool_call>
"""
    )

    assert action.kind == "invalid_tool"
    assert action.parse_error == "write tool call missing content"
    assert should_retry_malformed_tool_call(action) is False



def test_invalid_python_write_is_not_retryable():
    action = parse_assistant_action(
        """
<tool_call>
<name>write</name>
<arguments>
<path>server.py</path>
</arguments>
</tool_call>
<write_content>
```python
class A:
def broken(self):
pass
```
</write_content>
"""
    )

    assert action.kind == "invalid_tool"
    assert action.parse_error is not None
    assert "python write content failed syntax validation" in action.parse_error
    assert should_retry_malformed_tool_call(action) is False
