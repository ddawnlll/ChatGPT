from proxy.app.tools_shim import build_pi_agent_prompt, parse_assistant_action


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
        "command": "find app -print | sed 's|[^/]*/|  |g; s|  \\([^ ]\\)|├── \\1|'",
    }


def test_parse_xml_write_tool_call_with_raw_content():
    text = """
<tool_call>
<name>write</name>
<arguments>
<path>app/test.py</path>
<content>
print(\"hello world\")
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


def test_parse_multiple_xml_tool_calls_returns_tools_kind():
    text = """
<tool_call><name>find</name><arguments><path>.</path><pattern>*.py</pattern></arguments></tool_call>
<tool_call><name>grep</name><arguments><path>.</path><pattern>TODO</pattern></arguments></tool_call>
"""

    action = parse_assistant_action(text)

    assert action.kind == "tools"
    assert action.tool_calls is not None
    assert [call.name for call in action.tool_calls] == ["find", "grep"]


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
