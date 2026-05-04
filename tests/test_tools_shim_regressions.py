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
