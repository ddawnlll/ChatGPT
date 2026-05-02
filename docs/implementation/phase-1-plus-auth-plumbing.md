# Phase 1 — Auth/Session Plumbing for Plus-Capable API (Complete)

**Status:** Complete
**Owner:** API/runtime track
**Last updated:** 2026-05-02
**Delivery status:** Complete

---

## 1. Purpose

This phase completes the missing plumbing between the HTTP API and the underlying `ChatGPT` client so authenticated sessions can be represented, passed through, and reused consistently.

This phase is not about changing the core conversation flow or reverse-engineering logic; it is about making the current auth/cookie hooks usable from the API boundary and stable across requests.

---

## 2. What Carried Over / What Must Stay Stable

The following are already implemented / must remain stable:

- [x] Existing `/conversation` request/response shape for unauthenticated usage
- [x] Token/challenge flow in `wrapper/chatgpt.py` for the current web client path
- [x] Image upload and multimodal message support
- [x] Proxy normalization logic in `api_server.py`
- [x] Event-stream parsing and response assembly

This phase builds on top of these. Do not regress them.

---

## 3. Background & Motivation

The latest merge added partial auth support directly inside `wrapper/chatgpt.py`:

- `authorization` can now be injected into the client
- `cookies` can be passed into the client constructor
- the `Authorization` header is propagated across request phases

However, the API layer still does not expose those inputs, and there is no persistence model for a logged-in session. The result is a half-wired state: the client can accept auth material, but the server cannot yet manage it as a first-class concept.

The correct approach is to treat auth/session handling as a separate API concern and make the client consume a normalized session object rather than ad hoc per-call values.

---

## 4. Current Failure State / Known Blockers

The current state has the following known issues:

- `ConversationRequest` in `api_server.py` only accepts `proxy`, `message`, and `image` — there is no auth input surface.
- `ChatGPT.__init__()` accepts `authorization` and `cookies`, but those values are never supplied by the API server.
- Session state is recreated on every `/conversation` call, so any login/session material is not retained.
- There is no schema for cookie serialization/deserialization.
- There is no explicit handling for expired/invalid auth material.
- There is no model-selection or account-capability layer tied to authenticated sessions.

---

## 5. Workstream A — API Contract for Authenticated Sessions

**Status:** Complete

### Problem / Goal

Expose a stable request contract so callers can provide auth/session material explicitly instead of relying on implicit state.

### Root Cause (if applicable)

The API boundary currently strips away all session metadata, which makes the downstream auth hooks unusable.

### Implementation Tasks

- [x] Extend `ConversationRequest` to accept session material fields
- [x] Define a normalized format for `authorization` and `cookies`
- [x] Validate auth inputs early and return clear 4xx errors
- [x] Keep legacy unauthenticated calls working without changes

### Configuration / Code Reference (if applicable)

```python
class ConversationRequest(BaseModel):
    proxy: str
    message: str
    image: str | None = None
    session_id: str | None = None
    cookies: str | list[CookieItem] | dict[str, str] | None = None
    authorization: str | None = None
    thinking_mode: str | None = None
```

### Acceptance Criteria

- [x] The API can accept auth/session fields without breaking current callers
- [x] Invalid auth input is rejected before request execution
- [x] Existing unauthenticated requests still work

---

## 6. Workstream B — Session Persistence Layer

**Status:** Complete

### Problem / Goal

Keep auth state available across multiple API calls so a client can reuse the same session instead of rebuilding it every request.

### Implementation Tasks

- [x] Introduce a session key or client identifier in the API layer
- [x] Store session material in a small in-memory or file-backed cache
- [x] Rehydrate `ChatGPT` instances from stored session state
- [x] Add expiry / invalidation handling for stale sessions

### Configuration / Code Reference (if applicable)

```python
# conceptual shape only
{
  "session_id": "...",
  "proxy": "...",
  "authorization": "...",
  "cookies": {...},
  "last_used": 1234567890
}
```

### Acceptance Criteria

- [x] A caller can reuse the same auth/session state across multiple messages
- [x] Sessions expire or invalidate cleanly when stale
- [x] No cross-session leakage between different callers

---

## 7. Workstream C — Client Auth Wiring and Lifecycle

**Status:** Complete

### Problem / Goal

Make the existing `ChatGPT` auth hooks behave as a coherent lifecycle instead of one-off header injection.

### Implementation Tasks

- [x] Ensure `authorization` is only attached when present and valid
- [x] Clarify when cookies are merged vs. refreshed
- [x] Add a single session bootstrap path for auth-enabled clients
- [x] Separate auth/session bootstrap from challenge/token generation

### Configuration / Code Reference (if applicable)

```python
class ChatGPT:
    def __init__(self, proxy: str=None, cookies: dict = None, authorization: str = None, thinking_mode: str = "instant") -> Any:
        self.session: requests.session.Session = requests.Session(impersonate="chrome133a")
        self.authorization: str = authorization
        self.thinking_mode: str = thinking_mode
        if self.authorization:
            self.session.headers.update({'Authorization': self.authorization})
```

### Acceptance Criteria

- [x] Auth-enabled clients initialize without breaking the existing conversation flow
- [x] Cookie injection behavior is deterministic
- [x] Auth headers are not emitted accidentally when missing

---

## 8. Workstream D — Thinking Mode Selection

**Status:** Complete

### Problem / Goal

Let the API caller choose between `instant`, `extended`, and `pro` thinking modes while preserving the current default path.

### Implementation Tasks

- [x] Add a request field such as `thinking_mode`
- [x] Validate allowed values: `instant`, `extended`, `pro`
- [x] Map the selected mode into the conversation payload or runtime config
- [x] Define fallback behavior when the mode is unsupported

### Configuration / Code Reference (if applicable)

```python
{
  "thinking_mode": "instant"
}
```

### Acceptance Criteria

- [x] Caller can explicitly request `instant`
- [x] Caller can explicitly request `extended`
- [x] Caller can explicitly request `pro`
- [x] Invalid values are rejected cleanly
- [x] Existing default behavior still works unchanged

---

## 9. Workstream E — User-Supplied Session Material Import

**Status:** Complete

### Problem / Goal

Allow a caller to provide their own already-authenticated session material so the client can reuse that session without login automation.

### Non-Goals

- [x] Do not automate login or credential entry
- [x] Do not infer or extract secrets from a browser
- [x] Do not depend on app-specific telemetry, preferences, or debug state for authentication

### Implementation Tasks

- [x] Add a normalized input shape for user-supplied session material
- [x] Support cookie jar import from a user-provided payload
- [x] Support optional authorization material when required by the client
- [x] Store imported session material per session key
- [x] Redact sensitive session values from logs and error messages
- [x] Reject malformed or incomplete session payloads cleanly
- [x] Update the HTTP API schema to accept imported session fields
- [x] Update `manual.py` to load a local session fixture for offline testing

### Configuration / Code Reference (if applicable)

```ts
// Preferred structured form

type UserSessionMaterial = {
  session_id?: string;
  cookies?: string | Cookie[];
  authorization?: string;
  thinking_mode?: string;
};

type Cookie = {
  name: string;
  value: string;
  domain?: string;
  path?: string;
  expires?: string;
  httpOnly?: boolean;
  secure?: boolean;
  sameSite?: "Strict" | "Lax" | "None";
};
```

```python
# api_server.py (conceptual)
class ConversationRequest(BaseModel):
    message: str
    image: str = None
    session_id: str = None
    cookies: list[dict] | str = None
    authorization: str = None
    thinking_mode: str = "instant"
```

```python
# manual.py (conceptual)
with open("session.json", "r", encoding="utf-8") as f:
    session = load(f)

client = ChatGPT(
    cookies=session.get("cookies"),
    authorization=session.get("authorization"),
    thinking_mode=session.get("thinking_mode", "instant"),
)
```

### Acceptance Criteria

- [x] A user can provide session material from their own browser/session export
- [x] The HTTP API accepts imported session fields and forwards them to the client
- [x] `manual.py` can load a local session fixture without browser interaction
- [x] The API can reuse imported session state on subsequent calls
- [x] Raw session secrets are never echoed back in logs or errors
- [x] Invalid session payloads fail fast with clear validation errors

---

## 10. Workstream F — Test Coverage

**Status:** Complete
**Required before:** next release candidate

### 10.1 Request contract tests

- [x] Validate that the API accepts the new auth/session fields
- [x] Validate that legacy payloads still work
- [x] Validate that invalid payloads fail fast

### 10.2 Session lifecycle tests

- [x] Validate that session state can be reused across calls
- [x] Validate that expired sessions are rejected or refreshed

### 10.3 Client behavior tests

- [x] Validate that `ChatGPT` receives auth/session material from the API layer
- [x] Validate that unauthenticated behavior remains unchanged

---

## 11. Workstream G — Pre-Run / Pre-Deploy Audit Checklist

**Status:** Complete
**Must complete before:** release

### 11.1 Runtime config audit

- [x] Confirm auth/session fields are documented and consistent across API and client
- [x] Confirm proxy is optional and does not block local execution

### 11.2 State isolation audit

- [x] Confirm one caller cannot reuse another caller’s session by accident

### 11.3 Backward compatibility audit

- [x] Confirm existing callers can still use the API with only message

---

## 12. Combined Implementation Order

> List the workstreams in the exact sequence they must be executed. Explain any dependencies.

1. Complete Workstream A — API contract for authenticated sessions
2. Implement Workstream C — client auth wiring and lifecycle
3. Apply Workstream B — session persistence layer
4. Implement Workstream E — user-supplied session import
5. Run Workstream G — pre-run / pre-deploy audit
6. Implement Workstream F — test coverage
7. Execute an end-to-end smoke run
8. Evaluate results against acceptance criteria

### Acceptance Criteria for First Combined Run

- [x] Auth/session fields are accepted and passed through end-to-end
- [x] A second request can reuse the same stored session state
- [x] Legacy unauthenticated requests still succeed
- [x] No session data leaks between unrelated requests

---

## 13. Definition of Done

> Phase 1 is complete when **all** of the following are true simultaneously. No partial credit.

### 13.1 API layer

- [x] Existing `/conversation` route remains available
- [x] Proxy normalization remains intact
- [x] Auth/session fields are accepted by the API
- [x] Auth/session validation is explicit and documented

### 13.2 Client/runtime layer

- [x] `ChatGPT` can be initialized from persisted session state
- [x] Auth headers are handled consistently
- [x] Cookie/session lifecycle is deterministic

### 13.3 Candidate health

- [x] Multi-request session reuse works
- [x] Invalid sessions fail cleanly

### 13.4 Testing

- [x] Request contract tests exist
- [x] Session lifecycle tests exist
- [x] Backward compatibility tests exist

---

## 14. What Phase 2 Inherits

### 14.1 Capability expansion themes or inherited state

- A stable API contract for auth/session inputs
- A reusable session representation across requests
- A cleaner boundary between API, session management, and client execution

### 14.2 Phase Boundary

- Phase 2 is capability expansion on top of authenticated session plumbing.
- Phase 1 is the prerequisite.
- Do not start Phase 2 work until Phase 1 definition of done is fully satisfied.

---

## 15. Compact Mental Model

### 15.1 Phase Relationships

- Phase 0: existing reverse-engineered conversation flow
- Phase 1: make auth/session state a first-class API concept
- Phase 2: build whatever higher-level account capabilities depend on that state
- Phase 3: harden and scale the whole interface

### 15.2 Key Takeaway

The merge already introduced pieces of auth support inside the client, but the system still lacks a real session model. This phase turns those partial hooks into a coherent contract so the API can carry auth state without breaking existing behavior.
