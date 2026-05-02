# Phase 2 — Authenticated ChatGPT Web Flow Replacement for `backend-anon`

**Status:** In progress
**Owner:** API/runtime track
**Last updated:** 2026-05-02
**Delivery status:** First scaffolding pass complete

---

## 1. Purpose

This phase keeps the existing reverse-engineered ChatGPT web-wrapper architecture, but changes the primary runtime path from the current anonymous/`backend-anon` flow to a logged-in authenticated ChatGPT web flow.

The goal is **not** to migrate to the official OpenAI API as the primary backend.

The goal is:

- preserve the current ChatGPT web-wrapper architecture,
- preserve the current chat UX, persistence model, streaming behavior, and file handling model,
- replace `backend-anon` as the default path,
- use authenticated ChatGPT web session material supplied by the user,
- and make newly created conversations behave like normal account-backed ChatGPT conversations when feasible.

The intended end state is:

- `transport_mode="authenticated"` is the primary/default mode
- `transport_mode="anon"` remains available only as fallback/debug
- authenticated mode fails loudly when required session/auth material is missing unless `allow_anon_fallback=True` is explicitly set

---

## 2. Direction and Constraints

### Primary Direction

The project must continue to use the ChatGPT web-wrapper approach as its main architecture.

That means:

- browser-like request flow remains the core integration model
- session material remains user-supplied (`cookies`, `authorization`, device/client headers if needed)
- streaming remains based on the ChatGPT web event stream
- file support remains integrated with ChatGPT web upload/attachment behavior

### Explicit Constraints

This phase must **not**:

- [ ] make the official OpenAI API the main backend
- [ ] automate login
- [ ] extract browser secrets automatically
- [ ] bypass security or anti-abuse protections
- [ ] assume private endpoints are stable without diagnostics
- [ ] hardcode authenticated payload fields without first comparing them to real logged-in browser traffic
- [ ] silently fall back from authenticated mode to anon mode
- [ ] call `/backend-anon/...` endpoints from authenticated mode

### Expected Reality

Authenticated ChatGPT web flows are private and may be unstable. Even so, this phase intentionally chooses that path because the desired behavior is account-backed ChatGPT conversations, not a local-only provider abstraction.

---

## 3. What Carried Over / What Must Stay Stable

The following are already implemented and must remain stable through this phase:

- [x] current FastAPI chat CRUD endpoints
- [x] SQLite persistence for locally tracked chats/messages
- [x] React frontend chat experience
- [x] SSE streaming endpoint and live token/chunk rendering
- [x] image/file-capable message sending through the current wrapper model
- [x] session-material import via cookies/authorization
- [x] anon flow remains available for fallback/debug

This phase must not regress the current ability to:

- create chats
- send messages
- stream responses live
- persist local chat state
- attach images/files through the existing UI/server flow

---

## 4. Current Failure State / Motivation

The current wrapper is functionally able to obtain answers, continue conversations, and stream responses, but it is still built around anonymous web endpoints such as:

- `/backend-anon/sentinel/chat-requirements`
- `/backend-anon/f/conversation/prepare`
- `/backend-anon/f/conversation`
- `/backend-anon/files`
- `/backend-anon/files/process_upload_stream`

The current payloads also include fields such as:

- `history_and_training_disabled: True`

This is likely a major reason why chats do not appear as normal account-backed conversations in `chatgpt.com` history/sidebar even when user-provided session material is present.

The missing piece is not local persistence. The missing piece is that the main runtime path is still anon-oriented rather than authenticated-account-oriented.

---

## 5. Phase Goal

By the end of this phase, the system should:

- default to authenticated ChatGPT web transport
- use explicit user-provided session/auth material
- validate required session material before authenticated sends/streams
- mirror the logged-in browser request sequence closely enough to create and continue real account conversations when possible
- preserve current streaming and file behavior
- retain local persistence as an app-level cache/index
- fail loudly if authenticated mode is requested but required auth/session material is missing, unless `allow_anon_fallback=True` is explicitly enabled
- fall back to anon only when explicitly allowed or explicitly requested

---

## 6. Workstream A — Current Anon Flow Audit

**Status:** Complete

### Problem / Goal

Before changing the runtime path, we need a precise inventory of which parts of the current wrapper are truly anon-specific and which parts are reusable for authenticated flow.

### Implementation Tasks

- [x] Audit every `backend-anon` endpoint used in `wrapper/chatgpt.py`
- [x] Identify which headers are always sent today
- [x] Identify which payload fields are likely suppressing normal account-history behavior
- [x] Identify which flow stages are reusable regardless of auth mode
- [x] Produce a side-by-side map of current anon request sequence

### Areas to Inspect

- `get_chat_requirements` / sentinel token bootstrap
- conduit preparation
- initial conversation send
- continuation send
- streaming event parsing
- upload/create/process file calls
- state extraction for `conversation_id` / `parent_message_id`

### Acceptance Criteria

- [x] We have a documented map of the current anon flow
- [x] We know which pieces are transport-agnostic vs anon-specific
- [x] We have a concrete list of payload/header candidates to compare against authenticated browser traffic

### Audit Result — Current Anon Flow Inventory

The current anon implementation is now fully inventoried in code and diagnostics via `ChatGPT.get_transport_audit()`.

#### Anon endpoint family in use

- `/backend-anon/sentinel/chat-requirements`
- `/backend-anon/f/conversation/prepare`
- `/backend-anon/f/conversation`
- `/backend-anon/files`
- `/backend-anon/files/process_upload_stream`

#### Header inventory observed in the current wrapper

**Requirements stage**
- `oai-client-version`
- `oai-device-id`
- `Authorization`

**Prepare conversation stage**
- `oai-client-version`
- `oai-device-id`
- `Authorization`

**Conversation send / stream stage**
- `oai-client-version`
- `oai-device-id`
- `oai-echo-logs`
- `openai-sentinel-chat-requirements-token`
- `openai-sentinel-proof-token`
- `openai-sentinel-turnstile-token`
- `x-conduit-token`
- `Authorization`

**File creation / processing stages**
- `oai-client-version`
- `oai-device-id`
- `Authorization`

**File upload PUT stage**
- `Authorization`

#### Payload fields that are likely suppressing normal account-history behavior

Current high-risk field candidates:
- `history_and_training_disabled: True`

This field is present in:
- prepare-conversation payloads
- initial conversation payloads
- follow-up conversation payloads
- streaming conversation payloads

This remains the leading known payload-level candidate to compare against real logged-in browser traffic.

#### Reusable vs anon-specific flow stages

**Likely reusable across anon and authenticated modes**
- event-stream parsing
- response text chunk assembly
- `conversation_id` extraction
- `message_id` / parent message extraction
- local wrapper diagnostics
- local persistence integration in `api_server.py`
- image/file metadata assembly for outgoing message structures

**Clearly anon-specific today**
- `backend-anon` endpoint family
- sentinel requirements token bootstrap path
- conduit prepare path as currently wired
- turnstile / VM challenge token path as currently wired
- file create/process endpoints under `backend-anon`
- payloads carrying `history_and_training_disabled: True`

#### Current anon request sequence map

1. `GET https://chatgpt.com`
   - bootstrap cookies
   - extract `oai-did`
   - extract build/client version (`data-build`)

2. `POST /backend-anon/sentinel/chat-requirements`
   - send generated VM token payload `p`
   - receive:
     - chat requirements token
     - proof-of-work challenge
     - turnstile bytecode

3. `POST /backend-anon/f/conversation/prepare`
   - send lightweight conversation context
   - receive conduit token

4. Optional file flow when attachments are present
   - `POST /backend-anon/files`
   - upload returned file body to provided `upload_url`
   - `POST /backend-anon/files/process_upload_stream`

5. `POST /backend-anon/f/conversation`
   - initial send or follow-up send
   - sync or streaming depending on caller path

6. Parse event stream / response body
   - assemble assistant text
   - extract `conversation_id`
   - extract `message_id`
   - persist remote state locally

#### Output of Workstream A

Workstream A is complete for the current codebase. We now have:
- a coded anon endpoint inventory
- a coded header inventory
- a coded payload audit list
- a documented flow sequence
- a concrete comparison baseline for Workstream B browser-traffic discovery

---

## 7. Workstream B — Authenticated ChatGPT Web Endpoint Discovery from Browser Traffic

**Status:** In progress

### Problem / Goal

We must not guess the authenticated flow blindly. We need to compare against real logged-in browser network traffic.

### Constraints

- [ ] Use only user-observable browser devtools/network traffic
- [ ] Do not automate credential extraction
- [ ] Do not bypass protections
- [ ] Do not treat private endpoints as stable without diagnostics
- [ ] Do not route authenticated mode through any `/backend-anon/...` endpoint family

### Implementation Tasks

- [ ] Capture logged-in browser network traffic for: new chat, follow-up message, file upload, title update/sidebar appearance
- [ ] Identify the authenticated endpoint family used by the web app
- [ ] Record required request headers, cookies, and auth material
- [ ] Compare authenticated payloads against current anon payloads
- [ ] Identify which calls are required for chat creation vs continuation vs title/sidebar sync
- [ ] Identify whether file upload uses the same or different endpoint family in authenticated mode
- [ ] Document whether additional post-send calls are required for sidebar/history registration

### Diagnostic Targets

Filter browser network traffic for terms like:

- `conversation`
- `conversations`
- `backend`
- `history`
- `title`
- `files`
- `upload`
- `models`
- `session`

### Acceptance Criteria

- [ ] We have a concrete authenticated request sequence based on observed browser traffic
- [ ] Required headers/payload fields are documented
- [ ] Required post-send sync/title/history calls are documented if present
- [ ] The implementation plan for authenticated mode is based on observation, not guesses alone

---

## 8. Workstream C — `wrapper/chatgpt.py` Refactor into Anon vs Authenticated Paths

**Status:** In progress

### Problem / Goal

The current wrapper has one dominant path built around `backend-anon`. We need to preserve that code while introducing a clean authenticated path.

### Implementation Tasks

- [x] Introduce `transport_mode` in the wrapper constructor
- [x] Add `allow_anon_fallback=False` by default
- [x] Make `transport_mode="authenticated"` the default
- [x] Keep `transport_mode="anon"` as explicit fallback/debug mode
- [x] Split request construction into anon vs authenticated branches at the scaffolding boundary
- [x] Enforce that authenticated branches do not call any `/backend-anon/...` endpoints in the current scaffolding pass
- [x] Add an authenticated session validation step before any send/stream operation
- [ ] Separate shared logic from transport-specific logic:
  - event stream parsing
  - response extraction
  - conversation state updates
  - file metadata assembly
- [ ] Centralize header construction for each mode
- [x] Centralize endpoint selection for each mode
- [x] Add diagnostics showing which transport path was used and which required auth/session fields were present

### Configuration / Code Reference (target shape)

```python
class ChatGPT:
    def __init__(
        self,
        proxy: str | None = None,
        cookies: dict | None = None,
        authorization: str | None = None,
        thinking_mode: str = "instant",
        model_name: str = "auto",
        transport_mode: str = "authenticated",
        allow_anon_fallback: bool = False,
    ) -> None:
        ...
```

### Acceptance Criteria

- [x] Wrapper can execute either authenticated or anon flow explicitly
- [x] Shared parsing/state logic is not duplicated excessively
- [x] Authenticated mode is the default constructor behavior
- [x] Authenticated mode never silently routes into anon flow
- [x] Existing anon behavior remains usable for debugging/fallback

---

## 9. Workstream D — Authenticated Conversation Send

**Status:** In progress

### Problem / Goal

We need a logged-in initial conversation path that creates account-backed chats when feasible.

### Implementation Tasks

- [ ] Implement authenticated chat bootstrap using user-provided session material
- [x] Add explicit preflight session validation before authenticated sends
- [x] Validate and diagnose at minimum:
  - cookies present
  - authorization present if required
  - device/client headers present if required
- [ ] Implement authenticated initial conversation send
- [ ] Compare and adjust payload fields against real logged-in browser requests
- [ ] Remove or change fields that enforce non-history behavior, especially:
  - `history_and_training_disabled: True`
- [ ] Preserve conversation state extraction (`conversation_id`, message IDs, related metadata)
- [ ] Capture and persist any additional identifiers required for continuation
- [ ] Add defensive diagnostics for missing auth fields, unexpected response shapes, or alternate status codes

### Important Comparison Requirement

Do not hardcode the current anon payload into authenticated mode. Build authenticated request payloads from observed browser traffic.

### Acceptance Criteria

- [ ] Authenticated mode can send an initial message successfully
- [ ] Returned conversation state is captured and persisted
- [ ] Payload differs from anon mode where required by observed browser traffic
- [x] The request path does not include anon-only assumptions by default
- [x] Missing session/auth material produces loud, structured validation errors unless fallback is explicitly allowed

---

## 10. Workstream E — Authenticated Streaming

**Status:** In progress

### Problem / Goal

The app already has live streaming UX. Authenticated mode must preserve it.

### Implementation Tasks

- [ ] Implement authenticated streaming send path
- [x] Add explicit preflight session validation before authenticated streams
- [ ] Reuse the existing event-stream parser where compatible
- [ ] Adjust parser logic if authenticated stream framing differs from anon framing
- [ ] Preserve local SSE shape served by `api_server.py`
- [ ] Persist final assistant output and authenticated conversation state after stream completion
- [ ] Handle partial-stream failures cleanly

### Configuration / Code Reference (target shape)

```python
for chunk in client.stream_question(message):
    yield chunk
```

### Acceptance Criteria

- [ ] Frontend still receives incremental assistant text live
- [ ] Authenticated streams update stored conversation state correctly
- [ ] Stream completion produces stable persisted local chat state
- [ ] Authenticated mode does not regress the current UX

---

## 11. Workstream F — Authenticated File Upload

**Status:** In progress

### Problem / Goal

The wrapper already supports files/images, but the current upload path is anon-oriented. We need authenticated upload and attachment registration behavior.

### Implementation Tasks

- [ ] Discover the logged-in browser upload sequence for images/files
- [ ] Determine whether authenticated upload uses different endpoints, headers, or registration calls
- [ ] Implement authenticated upload/create/process steps
- [ ] Mirror attachment metadata fields expected by the logged-in conversation payload
- [ ] Preserve current app-level request shape (`message` + optional image/file input)
- [ ] Keep anon upload as fallback/debug implementation

### Acceptance Criteria

- [ ] Authenticated mode can attach supported files/images successfully
- [ ] Uploaded files are referenced correctly in authenticated conversation payloads
- [ ] The local app flow does not need a different UX for authenticated file sending

---

## 12. Workstream G — Conversation / Title / Sidebar History Verification

**Status:** In progress

### Problem / Goal

The point of authenticated mode is not just getting answers; it is getting normal account-backed ChatGPT conversations when feasible.

### Implementation Tasks

- [ ] Verify whether a new authenticated conversation appears in `chatgpt.com` sidebar/history
- [ ] Verify whether follow-up messages remain linked to the same remote conversation
- [ ] Verify whether remote conversation title is created automatically or requires additional calls
- [ ] Identify any metadata update/title/sidebar sync calls performed by the browser after first send
- [ ] Add structured diagnostics/logging for:
  - selected transport mode
  - endpoint family
  - remote conversation id
  - parent/message id
  - whether fallback occurred
  - whether sidebar/history verification passed, failed, or was not checked
- [ ] Compare local persisted title with remote sidebar title behavior

### Outcomes to Classify

For each tested flow, classify as:

- [ ] response works only
- [ ] response + remote conversation exists
- [ ] response + sidebar/history entry exists
- [ ] response + sidebar + stable continuation works

### Acceptance Criteria

- [ ] We can clearly tell whether authenticated flow produces true account-backed chat history
- [ ] Any missing sidebar/title sync stage is identified explicitly
- [ ] Diagnostics are strong enough to distinguish “answered” from “account conversation created”
- [ ] If sidebar/history parity is not achieved, the exact missing browser request stage is documented

---

## 13. Workstream H — Fallback to Anon Only When Authenticated Mode Is Unavailable

**Status:** In progress

### Problem / Goal

Authenticated mode should be primary, but anon mode still has diagnostic and fallback value.

### Implementation Tasks

- [x] Make authenticated mode the default everywhere new clients are built
- [x] Require explicit fallback conditions for anon mode, such as:
  - missing required auth/session material and `allow_anon_fallback=True`
  - authenticated flow explicitly disabled by caller
  - authenticated flow unavailable and fallback allowed
- [x] Add clear diagnostics when anon fallback occurs
- [x] Ensure anon fallback does not silently happen without visibility
- [x] Preserve current anon behavior as a controlled fallback/debug path

### Acceptance Criteria

- [ ] Authenticated mode is attempted first by default
- [ ] Anon mode is still available explicitly
- [ ] Fallback behavior is visible and diagnosable
- [ ] The app does not silently drop back to anon and confuse account-history expectations

---

## 14. API / Persistence Changes

## `api_server.py`

### Keep
- [ ] current chat CRUD endpoints
- [ ] current SSE streaming endpoint shape
- [ ] current local persistence model for chats/messages
- [ ] current session-material request structure as the basis for authenticated mode

### Change
- [x] Add `transport_mode` to request/session/chat creation models
- [x] Add `allow_anon_fallback` to request/session/chat creation models
- [x] Default `transport_mode` to `authenticated`
- [x] Default `allow_anon_fallback` to `False`
- [x] Pass transport mode into `ChatGPT` client construction
- [x] Persist transport mode per chat
- [ ] Persist authenticated remote conversation identifiers and related metadata
- [ ] Add clearer diagnostics for authenticated vs anon path selection

### Acceptance Criteria

- [ ] Server defaults to authenticated wrapper path
- [ ] Existing chat persistence still works
- [ ] Per-chat transport mode is explicit and inspectable

## Conversation Persistence

### Keep
- [ ] local SQLite storage of chats and messages

### Change
- [ ] continue persisting remote conversation IDs / message IDs
- [ ] expand persistence if authenticated flow requires additional remote identifiers
- [ ] track transport mode with each chat
- [ ] optionally track remote sync/title/sidebar verification state

### Example Additional Fields (conceptual)

```python
{
  "transport_mode": "authenticated",
  "allow_anon_fallback": False,
  "remote_conversation_id": "...",
  "remote_parent_message_id": "...",
  "remote_title_synced": False,
  "remote_sidebar_visible": False,
  "history_verification": "not_checked",  # passed | failed | not_checked
  "fallback_occurred": False,
}
```

### Acceptance Criteria

- [ ] Local DB can distinguish anon vs authenticated chats
- [ ] Authenticated continuation has enough stored remote state to resume correctly
- [ ] Verification metadata can be inspected during debugging

---

## 15. File-Level Change Plan

## `wrapper/chatgpt.py`

### Keep
- [ ] current reverse-engineered architecture
- [ ] current stream parsing utilities
- [ ] current file metadata assembly concepts
- [ ] current session diagnostics concepts

### Change
- [ ] introduce explicit transport split: authenticated vs anon
- [ ] replace default endpoint family from anon to authenticated
- [ ] build authenticated headers/payloads from browser-traffic observations
- [ ] keep anon implementation as fallback/debug
- [ ] add stronger diagnostics around conversation creation/history visibility assumptions

## `api_server.py`

### Keep
- [ ] current chat API shape
- [ ] streaming endpoint UX
- [ ] local SQLite persistence approach

### Change
- [ ] propagate `transport_mode`
- [ ] default to authenticated client creation
- [ ] persist transport-specific remote state and verification metadata
- [ ] improve logs/errors when authenticated state is incomplete or fallback occurs

## Frontend

### Keep
- [ ] current chat UX
- [ ] current streaming UX
- [ ] current create/select/delete/rename flow

### Change
- [ ] optionally expose transport mode in settings or debug UI
- [ ] optionally surface when a chat is running in fallback anon mode
- [ ] optionally surface remote sync diagnostics for testing

---

## 16. Recommended Implementation Order

### Step 1 — Audit and Discovery
- [x] audit the current anon wrapper flow in detail at the code/endpoint inventory level
- [ ] capture logged-in browser request flow for message send/continue/file upload/title/sidebar behavior
- [ ] document authenticated endpoint family, headers, and payloads

### Step 2 — Wrapper Refactor
- [x] add `transport_mode`
- [x] split anon vs authenticated request builders/endpoints at the scaffolding boundary
- [x] keep shared parsing/state logic centralized where already available

### Step 3 — Authenticated Message Path
- [ ] implement authenticated initial send
- [ ] implement authenticated continuation send
- [ ] remove/change non-history payload flags based on observed traffic

### Step 4 — Authenticated Streaming and Files
- [ ] implement authenticated streaming path
- [ ] implement authenticated upload/attachment path
- [ ] verify end-to-end UI behavior remains stable

### Step 5 — Verification and Fallback
- [ ] verify remote account conversation creation/title/sidebar visibility
- [ ] add structured diagnostics for authenticated vs anon path and remote sync state
- [ ] permit anon fallback only under explicit or diagnosable conditions
- [ ] document exact missing browser request stage if sidebar/history parity is not achieved

---

## 17. Acceptance Criteria for the Phase

This phase is complete when:

- [ ] `transport_mode="authenticated"` is the default path
- [ ] current app UX still works end-to-end
- [ ] authenticated mode can send and stream replies successfully
- [ ] authenticated mode can continue conversations with persisted remote IDs/state
- [ ] authenticated file/image upload works
- [ ] authenticated mode never calls `/backend-anon/...` endpoints
- [ ] anon mode remains available as fallback/debug only
- [ ] we can determine with evidence whether chats are appearing as account-backed ChatGPT history/sidebar entries
- [ ] either authenticated chats appear as real account-backed ChatGPT sidebar/history entries, or the exact missing browser request stage preventing parity is documented

---

## 18. Risks / Watchouts

- authenticated ChatGPT web endpoints are private and may change without notice
- browser traffic may include extra metadata or sync calls beyond the main conversation request
- file upload flow may differ materially between anon and authenticated modes
- missing one post-send sync/title/history request may cause “works but not in sidebar” behavior
- fallback to anon must be visible or it will recreate the current confusion
- current wrapper is large and will likely need careful incremental refactoring

---

## 19. Exit Decision

At the end of this phase, the repo should clearly reflect this direction:

- the project remains a ChatGPT web-wrapper system
- authenticated web flow is the primary/default transport
- anon web flow is fallback/debug only
- local persistence continues to exist as app-owned state
- the implementation either creates real account-backed conversations successfully, or documents precisely which authenticated browser stages are still missing for sidebar/history parity
