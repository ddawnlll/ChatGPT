import pytest

from proxy.app.streaming import chat_completions_stream


async def fake_chunks():
    yield "Re"
    yield "ady."


@pytest.mark.anyio
async def test_chat_completions_stream_contract():
    events = []

    async for event in chat_completions_stream(
        fake_chunks(),
        model="chatgpt-playwright",
        request_id="chatcmpl-test",
    ):
        events.append(event)

    assert events[0].startswith("data: ")
    assert '"id":"chatcmpl-test"' in events[0]
    assert '"object":"chat.completion.chunk"' in events[0]
    assert '"role":"assistant"' in events[0]
    assert '"content":"Re"' in events[0]

    assert '"content":"ady."' in events[1]
    assert '"finish_reason":"stop"' in events[-2]
    assert events[-1] == "data: [DONE]\n\n"
