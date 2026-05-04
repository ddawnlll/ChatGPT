from proxy.app.tools_shim import parse_assistant_action


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


def test_parse_plain_final_fallback():
    action = parse_assistant_action("Ready.")

    assert action.kind == "final"
    assert action.content == "Ready."


def test_parse_incomplete_final_response_tag_is_rejected():
    action = parse_assistant_action("<final")

    assert action.kind == "invalid_tool"
    assert action.parse_error == "incomplete final_response tag"


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
