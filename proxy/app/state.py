from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any

from transport_runtime import ChatTransport


@dataclass(slots=True)
class ConversationState:
    conversation_id: str
    transport: ChatTransport | None = None
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)
    data: dict[str, Any] = field(default_factory=dict)


class ConversationStore:
    def __init__(self) -> None:
        self._items: dict[str, ConversationState] = {}

    def get(self, conversation_id: str) -> ConversationState | None:
        return self._items.get(conversation_id)

    def put(self, state: ConversationState) -> None:
        state.updated_at = time()
        self._items[state.conversation_id] = state

    def delete(self, conversation_id: str) -> None:
        self._items.pop(conversation_id, None)

    def clear(self) -> None:
        self._items.clear()

    def count(self) -> int:
        return len(self._items)


conversation_store = ConversationStore()
