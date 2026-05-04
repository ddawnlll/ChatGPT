from __future__ import annotations

import importlib

from proxy.app import client as client_module
from proxy.app.state import ConversationState, conversation_store
from transport_runtime import TransportResult


class DummyTransport:
    def __init__(self, text: str = "<final_response>Ready.</final_response>"):
        self.data = {"conversation_id": None, "parent_message_id": None, "conversation_url": None}
        self.calls: list[dict[str, object]] = []
        self.text = text
        self._last_result = TransportResult(text=text, remote_conversation_id=None, remote_parent_message_id=None, transport_details={}, verification_hints={})

    def send_message(self, message, image=None, *, new_conversation=True):
        self.calls.append({"message": message, "new_conversation": new_conversation})
        self._last_result = TransportResult(
            text=self.text,
            remote_conversation_id="remote-next",
            remote_parent_message_id="msg-next",
            transport_details={"page_url": "https://chatgpt.com/c/remote-next"},
            verification_hints={},
        )
        return self._last_result

    def stream_message(self, message, image=None, *, new_conversation=True):
        yield self.text

    def get_last_result(self):
        return self._last_result



def test_config_default_agent_force_new_conversation_false(monkeypatch):
    monkeypatch.delenv("CHATGPT_PROXY_AGENT_FORCE_NEW_CONVERSATION", raising=False)
    from proxy.app import config as config_module

    reloaded = importlib.reload(config_module)
    try:
        assert reloaded.settings.agent_force_new_conversation is False
    finally:
        importlib.reload(config_module)



def test_config_env_agent_force_new_conversation_true(monkeypatch):
    monkeypatch.setenv("CHATGPT_PROXY_AGENT_FORCE_NEW_CONVERSATION", "true")
    from proxy.app import config as config_module

    reloaded = importlib.reload(config_module)
    try:
        assert reloaded.settings.agent_force_new_conversation is True
    finally:
        monkeypatch.delenv("CHATGPT_PROXY_AGENT_FORCE_NEW_CONVERSATION", raising=False)
        importlib.reload(config_module)



def test_runtime_client_reuses_saved_remote_thread_identity(monkeypatch):
    conversation_store.clear()
    state = ConversationState(
        conversation_id="conv-state",
        data={
            "remote_conversation_id": "remote-old",
            "remote_parent_message_id": "msg-old",
            "remote_conversation_url": "https://chatgpt.com/c/remote-old",
        },
    )
    state.transport = DummyTransport()
    conversation_store.put(state)

    runtime = client_module.RuntimeClient("chatgpt-playwright")
    text, effective = runtime.complete_chat_turn(
        messages=[{"role": "user", "content": "hi"}],
        conversation_id="conv-state",
        force_new_conversation=False,
    )

    assert text == "<final_response>Ready.</final_response>"
    assert effective == "conv-state"
    assert state.transport.calls[-1]["new_conversation"] is False
    assert state.transport.data["conversation_id"] == "remote-old"
    assert state.transport.data["parent_message_id"] == "msg-old"
    assert state.transport.data["conversation_url"] == "https://chatgpt.com/c/remote-old"



def test_runtime_client_force_new_conversation_clears_remote_thread_identity(monkeypatch):
    conversation_store.clear()
    state = ConversationState(
        conversation_id="conv-state",
        data={
            "remote_conversation_id": "remote-old",
            "remote_parent_message_id": "msg-old",
            "remote_conversation_url": "https://chatgpt.com/c/remote-old",
        },
    )
    state.transport = DummyTransport()
    conversation_store.put(state)

    runtime = client_module.RuntimeClient("chatgpt-playwright")
    _text, _effective = runtime.complete_chat_turn(
        messages=[{"role": "user", "content": "hi"}],
        conversation_id="conv-state",
        force_new_conversation=True,
    )

    assert state.transport.calls[-1]["new_conversation"] is True
    assert state.transport.data["conversation_id"] is None
    assert state.transport.data["parent_message_id"] is None
    assert state.transport.data["conversation_url"] is None
    stored = conversation_store.get("conv-state")
    assert stored is not None
    assert stored.data["remote_conversation_id"] == "remote-next"
    assert stored.data["remote_conversation_url"] == "https://chatgpt.com/c/remote-next"



def test_runtime_client_persists_page_url_after_response(monkeypatch):
    conversation_store.clear()
    transport = DummyTransport()
    monkeypatch.setattr(client_module, "build_transport", lambda session_material: transport)

    runtime = client_module.RuntimeClient("chatgpt-playwright")
    _text, effective = runtime.complete_chat_turn(
        messages=[{"role": "user", "content": "hi"}],
        conversation_id="conv-state",
        force_new_conversation=False,
    )

    stored = conversation_store.get(effective)
    assert stored is not None
    assert stored.data["remote_conversation_id"] == "remote-next"
    assert stored.data["remote_conversation_url"] == "https://chatgpt.com/c/remote-next"
