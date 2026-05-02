# Phase 2 — Official API Transport and Legacy Web-Flow Isolation

**Status:** Planned
**Owner:** API/runtime track
**Last updated:** 2026-05-02
**Delivery status:** Not started

---

## 1. Purpose

This phase changes the project direction from a reverse-engineered ChatGPT web wrapper into a maintainable multi-transport chat system with an official API-first architecture.

The primary goal is **not** to make the current `backend-anon` flow show up in `chatgpt.com` history. The goal is to:

- use the official OpenAI API for model interaction,
- keep our own application-owned chat history,
- preserve streaming and file support,
- isolate the current reverse-engineered ChatGPT web flow as a legacy/debug transport,
- and treat any authenticated ChatGPT web traffic work as explicitly experimental.

---

## 2. Feasibility Statement / Supported vs Unsupported

### Supported / Maintainable

The supported and maintainable direction is:

- official OpenAI API for completions / responses / streaming
- application-owned persistence for chats, messages, titles, attachments, and metadata
- provider-specific remote IDs stored as internal transport state

### Unsupported as a Public Product Surface

There is no supported public API whose purpose is:

- creating a conversation directly in the consumer `chatgpt.com` sidebar/history
- managing ChatGPT web account history as an application integration target

Therefore:

- official ChatGPT sidebar/history sync must be treated as **unsupported**
- private ChatGPT web endpoints must **not** become the main architecture
- any exploration of logged-in ChatGPT web traffic must remain **experimental only**

---

## 3. What Carried Over / What Must Stay Stable

The following are already implemented and must remain stable through this phase:

- [x] Local chat CRUD API in `api_server.py`
- [x] SQLite-backed persistence for chats/messages
- [x] React frontend chat list/detail flow
- [x] SSE-based streaming UX in the frontend/backend
- [x] Session-material handling for the existing wrapper
- [x] Legacy reverse-engineered chat path continues to function as a fallback

This phase must preserve current usability while changing the default architecture.

---

## 4. Current State Summary

The current implementation still assumes the reverse-engineered ChatGPT web flow is the main backend path:

- `wrapper/chatgpt.py` is tightly coupled to `backend-anon` endpoints
- transport state is effectively ChatGPT-web-specific (`conversation_id`, `parent_message_id`)
- file upload handling is tied to ChatGPT web upload endpoints
- persistence fields are shaped around the current wrapper rather than a provider-agnostic model
- the server builds `ChatGPT` clients directly instead of using a transport abstraction

This architecture is functional for legacy/debug usage, but it is not the right long-term foundation.

---

## 5. Non-Goals

This phase does **not** attempt to:

- [ ] guarantee ChatGPT web sidebar/history sync
- [ ] treat private `chatgpt.com` web endpoints as stable product dependencies
- [ ] automate login or extract session material from a browser
- [ ] bypass security, anti-abuse, or account protections
- [ ] remove the legacy path before the official transport exists

---

## 6. Workstream A — Transport Abstraction Layer

**Status:** Planned

### Problem / Goal

`api_server.py` currently depends directly on one reverse-engineered implementation. We need a provider-agnostic transport interface so the server can work with:

- official OpenAI transport
- legacy anon web transport
- experimental authenticated web transport

### Implementation Tasks

- [ ] Define a transport interface or protocol for chat operations
- [ ] Add transport selection via `transport_mode`
- [ ] Move provider-specific state behind transport methods
- [ ] Ensure both sync and streaming calls use the same abstraction
- [ ] Keep the current wrapper available as `anon_legacy`

### Configuration / Code Reference (target shape)

```python
class ChatTransport(Protocol):
    def send_message(self, message: str, image: str | None = None) -> dict: ...
    def stream_message(self, message: str, image: str | None = None): ...
    def export_state(self) -> dict: ...
    def import_state(self, state: dict) -> None: ...
```

```python
transport_mode: Literal[
    "openai",
    "anon_legacy",
    "authenticated_experimental",
]
```

### Acceptance Criteria

- [ ] `api_server.py` no longer depends directly on one transport implementation
- [ ] New chats can choose a transport mode explicitly
- [ ] Legacy behavior remains callable through `anon_legacy`
- [ ] Streaming works through the shared transport interface

---

## 7. Workstream B — Official OpenAI Transport

**Status:** Planned

### Problem / Goal

The project needs a maintainable primary backend that does not depend on reverse-engineered ChatGPT web traffic.

### Implementation Tasks

- [ ] Implement a new official transport using the OpenAI API
- [ ] Support normal request/response chat interaction
- [ ] Support streaming token/text delivery
- [ ] Support model selection through the existing API surface
- [ ] Support conversation continuity using provider state/response chaining
- [ ] Normalize transport results into the same app-level message format used by the UI

### Notes

The exact SDK or HTTP client can be chosen during implementation, but the design target is:

- official API for inference
- app-owned conversation persistence
- provider IDs stored as transport state, not as the source of truth for history

### Acceptance Criteria

- [ ] A chat can run fully without `backend-anon`
- [ ] A streamed assistant response reaches the current SSE endpoint
- [ ] The app can persist and resume official-provider conversation state
- [ ] The frontend does not need provider-specific logic

---

## 8. Workstream C — Legacy Anon Mode Isolation

**Status:** Planned

### Problem / Goal

The current reverse-engineered wrapper is still useful for diagnostics and compatibility, but it should no longer define the main architecture.

### Implementation Tasks

- [ ] Reclassify current wrapper behavior as `transport_mode="anon_legacy"`
- [ ] Keep existing auth/session diagnostics for this mode
- [ ] Keep current file/image support for this mode
- [ ] Stop making legacy transport assumptions part of the generic persistence model
- [ ] Document clearly that this mode is legacy/debug and may not create official ChatGPT history

### Acceptance Criteria

- [ ] Existing wrapper flow still works when explicitly selected
- [ ] Default path no longer requires legacy web-flow mechanics
- [ ] Legacy transport limitations are documented clearly

---

## 9. Workstream D — Experimental Authenticated Web Transport

**Status:** Planned

### Problem / Goal

If authenticated ChatGPT web traffic is explored at all, it must be isolated and explicitly marked as experimental.

### Constraints

- [ ] Explicit opt-in only
- [ ] Requires user-provided session/auth material
- [ ] No guarantee of stability or history sync
- [ ] No security-bypass framing or implementation
- [ ] No hardcoded assumption that private endpoints are stable

### Implementation Tasks

- [ ] Introduce `transport_mode="authenticated_experimental"`
- [ ] Reuse existing session material plumbing where applicable
- [ ] Add explicit documentation of fragility and unsupported status
- [ ] Keep any web-specific code isolated from the official transport path
- [ ] Add diagnostics to inspect what remote state, if any, was created

### Acceptance Criteria

- [ ] Experimental mode is clearly separated from supported modes
- [ ] Experimental mode cannot be confused with a supported official integration
- [ ] Main app behavior does not depend on this mode

---

## 10. Workstream E — Persistence Model Migration

**Status:** Planned

### Problem / Goal

The current DB schema stores ChatGPT-web-specific remote fields. We need a provider-agnostic persistence model.

### Current Fields to Deprecate

These should be treated as legacy-only fields:

- `remote_conversation_started`
- `remote_conversation_id`
- `remote_parent_message_id`

### Implementation Tasks

- [ ] Add `transport_mode` to chat persistence
- [ ] Add `transport_state_json` for provider-specific serialized state
- [ ] Add `history_source` and/or similar metadata fields
- [ ] Keep old remote fields only for migration/backward compatibility initially
- [ ] Load/save transport state through the transport abstraction instead of direct wrapper field access

### Configuration / Code Reference (target shape)

```sql
ALTER TABLE chats ADD COLUMN transport_mode TEXT NOT NULL DEFAULT 'openai';
ALTER TABLE chats ADD COLUMN transport_state_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE chats ADD COLUMN history_source TEXT NOT NULL DEFAULT 'local';
```

### Acceptance Criteria

- [ ] New chats persist provider state generically
- [ ] Old legacy chats can still load without data loss
- [ ] The DB schema no longer assumes ChatGPT web conversation semantics for all providers

---

## 11. Workstream F — Streaming Normalization

**Status:** Planned

### Problem / Goal

Streaming already works end-to-end in the app, but event normalization currently depends on wrapper-specific chunk behavior.

### Implementation Tasks

- [ ] Standardize transport streaming events into a common internal format
- [ ] Keep SSE output shape stable for the frontend
- [ ] Persist final assistant output and transport state after stream completion
- [ ] Handle partial failure cleanly without corrupting local chat history
- [ ] Support both official and legacy transports through the same streaming API

### Configuration / Code Reference (target shape)

```python
{"type": "user", "message": {...}}
{"type": "chunk", "content": "..."}
{"type": "done", "chat": {...}}
{"type": "error", "error": "..."}
```

### Acceptance Criteria

- [ ] Frontend keeps the same streaming UX
- [ ] Provider-specific event parsing is hidden behind the transport layer
- [ ] Failed streams leave local chat state consistent

---

## 12. Workstream G — File Upload and Attachment Metadata

**Status:** Planned

### Problem / Goal

File handling is currently tied to ChatGPT web endpoints. The app needs a provider-agnostic attachment model.

### Implementation Tasks

- [ ] Introduce persisted attachment metadata separate from provider-specific upload flows
- [ ] Support image/file inputs for the official transport where available
- [ ] Keep legacy upload behavior isolated in `anon_legacy`
- [ ] Store provider file IDs and local metadata in a normalized structure
- [ ] Decide whether attachments live in a dedicated DB table or serialized JSON

### Configuration / Code Reference (target shape)

```sql
CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER,
    provider_file_id TEXT,
    storage_path TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
```

### Acceptance Criteria

- [ ] Official transport can associate files/images with a message in a maintainable way
- [ ] Legacy upload code is no longer the generic app-level file model
- [ ] Attachment metadata survives restart and reload

---

## 13. Workstream H — Title and History Metadata Ownership

**Status:** Planned

### Problem / Goal

Titles and history behavior should be app-owned rather than inferred from ChatGPT web behavior.

### Implementation Tasks

- [ ] Keep first-message title derivation as fallback
- [ ] Add metadata such as `title_source`
- [ ] Optionally add generated-title support after first response
- [ ] Add `history_source` to make it explicit whether history is local, legacy, or experimental
- [ ] Keep title generation independent from any ChatGPT web sidebar assumptions

### Configuration / Code Reference (target shape)

```python
{
  "title": "How to build a calculator app",
  "title_source": "first_message",  # manual | first_message | generated
  "history_source": "local"         # local | legacy_anon | experimental_auth
}
```

### Acceptance Criteria

- [ ] Chats have explicit title/history ownership metadata
- [ ] Titles remain useful without relying on provider-generated chat titles
- [ ] The app remains the source of truth for history presentation

---

## 14. File-Level Change Plan

## `wrapper/chatgpt.py`

### Keep
- [ ] Existing reverse-engineered flow implementation
- [ ] Existing session diagnostics
- [ ] Existing legacy stream parsing utilities

### Change
- [ ] Reframe as legacy transport implementation rather than default architecture
- [ ] Add compatibility layer or move logic behind a transport interface
- [ ] Stop using this file as the only runtime backend abstraction

### Potential Follow-Up Split
- [ ] `wrapper/transports/anon_legacy.py`
- [ ] `wrapper/transports/openai_api.py`
- [ ] `wrapper/transports/authenticated_experimental.py`

## `api_server.py`

### Keep
- [ ] Chat CRUD endpoints
- [ ] SSE endpoint shape
- [ ] session-material normalization flow

### Change
- [ ] Add `transport_mode` to request models
- [ ] Replace `build_client()` with transport construction
- [ ] Replace direct wrapper state persistence with `transport_state_json`
- [ ] Migrate stream/send handlers to transport-agnostic logic

## Conversation Persistence

### Keep
- [ ] SQLite `chats` and `messages`

### Change
- [ ] Add provider-agnostic transport state storage
- [ ] Add optional attachment persistence
- [ ] Deprecate legacy-only remote conversation fields over time

## Streaming

### Keep
- [ ] frontend streaming UX
- [ ] backend SSE response shape

### Change
- [ ] normalize provider events through transport interface
- [ ] persist transport state after stream completion

## File Upload Handling

### Keep
- [ ] current image/file support as a legacy capability

### Change
- [ ] introduce a normalized attachment model
- [ ] implement official provider upload path separately

## Title / History Metadata

### Keep
- [ ] current first-message title fallback

### Change
- [ ] track title/history ownership explicitly in persistence
- [ ] avoid relying on ChatGPT web-generated titles/history semantics

---

## 15. Recommended Implementation Order

### Step 1 — Architecture Scaffold
- [ ] Add `transport_mode` to the API contract and persistence model
- [ ] Introduce transport interface/protocol
- [ ] Adapt current wrapper into `anon_legacy`

### Step 2 — Primary Supported Backend
- [ ] Implement official OpenAI transport
- [ ] Wire sync + streaming through the new transport abstraction
- [ ] Persist official-provider transport state locally

### Step 3 — Data Model Hardening
- [ ] Add `transport_state_json`
- [ ] add attachment metadata persistence
- [ ] add title/history ownership metadata

### Step 4 — Optional Experimental Layer
- [ ] Add `authenticated_experimental` mode only if explicitly requested
- [ ] document fragility and unsupported nature

---

## 16. Acceptance Criteria for the Phase

This phase is complete when:

- [ ] `openai` is the default supported transport mode
- [ ] Local chat history no longer depends on ChatGPT web history behavior
- [ ] SSE streaming works through the official transport
- [ ] Legacy anon mode still works when explicitly selected
- [ ] Experimental authenticated web mode, if implemented, is clearly isolated and documented as unsupported/fragile
- [ ] The persistence model is provider-agnostic enough to support official API evolution without another schema rewrite

---

## 17. Risks / Watchouts

- Private ChatGPT web traffic may change without notice
- Official API semantics may differ from the current wrapper's conversation model
- File support may require additional schema and UI work beyond the current base64-only image path
- Migration must not break existing persisted chats or current frontend expectations
- The current wrapper file is large and may need incremental extraction rather than one-shot replacement

---

## 18. Exit Decision

At the end of this phase, the repo should clearly communicate:

- the supported path is official API + app-owned persistence
- ChatGPT web sidebar/history sync is unsupported as a public integration target
- legacy reverse-engineered flows remain available only as fallback/debug tools
- authenticated ChatGPT web exploration, if present, is experimental and not the product foundation
