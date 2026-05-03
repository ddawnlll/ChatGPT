from __future__ import annotations

import json
from dataclasses import dataclass, field
from time import time
from typing import Any

from transport_runtime import ChatTransport

from .config import settings


@dataclass(slots=True)
class ConversationState:
    conversation_id: str
    transport: ChatTransport | None = None
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)
    data: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "data": dict(self.data),
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "ConversationState":
        return cls(
            conversation_id=str(payload.get("conversation_id", "")),
            created_at=float(payload.get("created_at", time())),
            updated_at=float(payload.get("updated_at", time())),
            data=dict(payload.get("data") or {}),
        )


class ConversationStore:
    def __init__(self) -> None:
        self._items: dict[str, ConversationState] = {}
        self._history_aliases: dict[str, str] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        path = settings.state_path()
        if not path.exists():
            self._loaded = True
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            self._loaded = True
            return
        for item in payload.get("conversations", []) or []:
            try:
                state = ConversationState.from_json(item)
            except Exception:
                continue
            if state.conversation_id:
                self._items[state.conversation_id] = state
        self._history_aliases = {
            str(alias): str(conversation_id)
            for alias, conversation_id in (payload.get("history_aliases") or {}).items()
            if alias and conversation_id
        }
        self._loaded = True

    def _persist(self) -> None:
        path = settings.state_path()
        payload = {
            "conversations": [state.to_json() for state in self._items.values()],
            "history_aliases": dict(self._history_aliases),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, conversation_id: str) -> ConversationState | None:
        self._ensure_loaded()
        return self._items.get(conversation_id)

    def get_by_history_alias(self, alias: str) -> ConversationState | None:
        self._ensure_loaded()
        conversation_id = self._history_aliases.get(alias)
        if not conversation_id:
            return None
        return self._items.get(conversation_id)

    def put(self, state: ConversationState) -> None:
        self._ensure_loaded()
        state.updated_at = time()
        self._items[state.conversation_id] = state
        self._persist()

    def bind_history_alias(self, alias: str, conversation_id: str) -> None:
        self._ensure_loaded()
        if alias:
            self._history_aliases[alias] = conversation_id
            self._persist()

    def delete(self, conversation_id: str) -> None:
        self._ensure_loaded()
        self._items.pop(conversation_id, None)
        aliases_to_drop = [alias for alias, bound_id in self._history_aliases.items() if bound_id == conversation_id]
        for alias in aliases_to_drop:
            self._history_aliases.pop(alias, None)
        self._persist()

    def clear(self) -> None:
        self._ensure_loaded()
        self._items.clear()
        self._history_aliases.clear()
        self._persist()

    def count(self) -> int:
        self._ensure_loaded()
        return len(self._items)


conversation_store = ConversationStore()
