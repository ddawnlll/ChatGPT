# Phase 2 — Direct ChatGPT Runtime Integration

**Status:** Complete
**Owner:** Proxy/runtime integration track
**Last updated:** 2026-05-03
**Delivery status:** Complete

---

## 1. Purpose

This phase connects the proxy directly to the local ChatGPT runtime.

Unlike the existing app server, the proxy must call the runtime **in-process**, using `transport_runtime.py` / `wrapper/chatgpt.py`, rather than calling `api_server.py` over HTTP.

---

## 2. What Carried Over / What Must Stay Stable

- [x] Phase 1 compatibility shell
- [x] `build_transport(...)` as the preferred transport creation boundary
- [x] Playwright-first runtime strategy
- [x] `transport_mode` semantics already used in this repo
- [x] no regression in direct runtime behavior

---

## 3. Background & Motivation

The proxy must translate OpenAI-style requests into direct local transport calls.

That means it needs its own:

- runtime client wrapper
- conversation/session state mapping
- model-to-runtime mapping
- streaming bridge

This phase is where the proxy stops being just a shell and becomes functional.

---

## 4. Current Failure State / Known Blockers

Original blockers were:

- there was no `proxy/app/client.py` that wrapped `build_transport(...)`
- there was no in-memory conversation state for OpenAI-style clients
- there was no mapping from OpenAI message arrays to local conversation continuation
- there was no direct streaming bridge from runtime chunks to OpenAI SSE

These are now resolved.

---

## 5. Workstream A — Runtime Client Wrapper

**Status:** Complete

### Problem / Goal

Create a dedicated proxy-side runtime client wrapper over `build_transport(...)`.

### Implementation Tasks

- [x] Add a proxy-local `RuntimeClient` abstraction
- [x] Normalize session material inputs for the proxy
- [x] Build transports through `build_transport(...)`
- [x] Prefer `playwright` by default
- [x] Expose both non-streaming and streaming methods

### Acceptance Criteria

- [x] proxy can create a transport from configured session material
- [x] proxy can send one message directly through runtime
- [x] proxy can stream one message directly through runtime

---

## 6. Workstream B — Conversation State Mapping

**Status:** Complete

### Problem / Goal

Map OpenAI-style request continuity to local runtime continuity.

### Implementation Tasks

- [x] Add in-memory conversation store
- [x] Track proxy conversation IDs / response IDs
- [x] Reuse transport/client instances when appropriate
- [x] Carry remote conversation IDs through runtime state
- [x] Define behavior for brand-new vs continuing chats

### Acceptance Criteria

- [x] repeated requests can continue the same local runtime state
- [x] new conversations do not accidentally reuse old runtime state
- [x] no cross-conversation leakage

---

## 7. Workstream C — `/v1/chat/completions` Direct Execution

**Status:** Complete

### Problem / Goal

Make `POST /v1/chat/completions` execute directly against the runtime.

### Implementation Tasks

- [x] Extract latest actionable user prompt from request
- [x] decide whether this is a new or continuing conversation
- [x] invoke runtime non-streaming path when `stream=false`
- [x] invoke runtime streaming path when `stream=true`
- [x] return OpenAI-shaped response payloads

### Acceptance Criteria

- [x] non-streaming chat completions work end-to-end
- [x] streaming chat completions work end-to-end
- [x] assistant text matches runtime output

---

## 8. Workstream D — Model / Config Mapping

**Status:** Complete

### Problem / Goal

Map proxy model identifiers to local runtime session material.

### Implementation Tasks

- [x] define initial static model aliases
- [x] map model IDs to:
  - `transport_mode`
  - `thinking_mode`
  - `model_name`
- [x] define safe defaults for omitted fields
- [x] keep config explicit and documented

### Acceptance Criteria

- [x] model IDs resolve deterministically
- [x] runtime receives the intended transport/thinking/model values

---

## 9. Workstream E — Session Material Strategy

**Status:** Complete

### Problem / Goal

Decide how the proxy acquires auth/browser settings.

### Implementation Tasks

- [x] define config source for cookies/auth/browser profile fields
- [x] reuse existing session conventions from this repo where possible
- [x] decide whether proxy is single-user or keyed multi-profile in Phase 2
- [x] redact sensitive values in logs/debug output

### Acceptance Criteria

- [x] proxy can start with usable runtime session material
- [x] secrets are not printed raw

---

## 10. Workstream F — Direct Runtime Tests

**Status:** Complete

### Implementation Tasks

- [x] mock transport construction tests
- [x] chat completion response-shaping tests
- [x] streaming conversion tests against runtime chunk inputs
- [x] conversation reuse tests

### Acceptance Criteria

- [x] runtime integration is covered without depending on live browser execution

### Validation Results

- [x] `python3 -m py_compile proxy/app/*.py proxy/tests/*.py`
- [x] `.venv-test/bin/pytest -q proxy/tests/test_proxy_phase1.py`
- [x] Current result: `10 passed`

---

## 11. Live Runtime Smoke Validation

**Status:** Complete

### Goal

Prove the proxy-side runtime path works against the real Playwright-backed browser transport, not only mocked transports.

### Validation

- [x] `node --check tools/playwright_chat_transport.mjs`
- [x] `.venv/bin/python - <<'PY' ... RuntimeClient('chatgpt-playwright').complete_chat(...) ... PY`
- [x] real response returned: `PROXY_SMOKE_OK`

### Meaning

This verifies that:

- the proxy-side runtime client can build a real transport
- the Playwright path can execute from the proxy integration boundary
- the first live end-to-end path works beyond mocks

---

## 12. Combined Implementation Order

1. Add runtime client wrapper
2. Add conversation state mapping
3. Implement direct `/v1/chat/completions`
4. Implement model/config mapping
5. Add session material strategy
6. Add tests
7. Run local end-to-end smoke checks

### Acceptance Criteria for First Combined Run

- [x] one-shot non-streaming call works
- [x] one-shot streaming call works
- [x] continuing conversation works
- [x] new conversation isolation works

---

## 13. Definition of Done

### 13.1 Runtime integration

- [x] proxy directly uses local runtime code
- [x] no `api_server.py` dependency exists in request execution path

### 13.2 Conversation handling

- [x] new vs continuing conversation behavior is explicit
- [x] state reuse is deterministic

### 13.3 Compatibility

- [x] `/v1/chat/completions` works for both streaming and non-streaming clients

### 13.4 Testing

- [x] direct runtime integration tests exist
- [x] live runtime smoke validation has been performed

---

## 14. What Phase 3 Inherits

Phase 3 inherits:

- a working direct-runtime OpenAI-compatible proxy
- basic model/config resolution
- in-memory conversation continuity
- validated first-pass live Playwright runtime execution

Phase 3 focuses on pi compatibility validation and higher-level agent usage.
