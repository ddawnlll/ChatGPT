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
        self._history_aliases: dict[str, str] = {}

    def get(self, conversation_id: str) -> ConversationState | None:
        return self._items.get(conversation_id)

    def get_by_history_alias(self, alias: str) -> ConversationState | None:
        conversation_id = self._history_aliases.get(alias)
        if not conversation_id:
            return None
        return self._items.get(conversation_id)

    def put(self, state: ConversationState) -> None:
        state.updated_at = time()
        self._items[state.conversation_id] = state

    def bind_history_alias(self, alias: str, conversation_id: str) -> None:
        if alias:
            self._history_aliases[alias] = conversation_id

    def delete(self, conversation_id: str) -> None:
        self._items.pop(conversation_id, None)
        aliases_to_drop = [alias for alias, bound_id in self._history_aliases.items() if bound_id == conversation_id]
        for alias in aliases_to_drop:
            self._history_aliases.pop(alias, None)

    def clear(self) -> None:
        self._items.clear()
        self._history_aliases.clear()

    def count(self) -> int:
        return len(self._items)


conversation_store = ConversationStore()
