# Phase 2 — Direct ChatGPT Runtime Integration

**Status:** Planned
**Owner:** Proxy/runtime integration track
**Last updated:** 2026-05-03
**Delivery status:** Not started

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

- There is no `proxy/app/client.py` that wraps `build_transport(...)`
- There is no in-memory conversation state for OpenAI-style clients
- There is no mapping from OpenAI message arrays to local conversation continuation
- There is no direct streaming bridge from runtime chunks to OpenAI SSE

---

## 5. Workstream A — Runtime Client Wrapper

**Status:** Planned

### Problem / Goal

Create a dedicated proxy-side runtime client wrapper over `build_transport(...)`.

### Implementation Tasks

- [ ] Add a proxy-local `RuntimeClient` abstraction
- [ ] Normalize session material inputs for the proxy
- [ ] Build transports through `build_transport(...)`
- [ ] Prefer `playwright` by default
- [ ] Expose both non-streaming and streaming methods

### Acceptance Criteria

- [ ] proxy can create a transport from configured session material
- [ ] proxy can send one message directly through runtime
- [ ] proxy can stream one message directly through runtime

---

## 6. Workstream B — Conversation State Mapping

**Status:** Planned

### Problem / Goal

Map OpenAI-style request continuity to local runtime continuity.

### Implementation Tasks

- [ ] Add in-memory conversation store
- [ ] Track proxy conversation IDs / response IDs
- [ ] Reuse transport/client instances when appropriate
- [ ] Carry remote conversation IDs through runtime state
- [ ] Define behavior for brand-new vs continuing chats

### Acceptance Criteria

- [ ] repeated requests can continue the same local runtime state
- [ ] new conversations do not accidentally reuse old runtime state
- [ ] no cross-conversation leakage

---

## 7. Workstream C — `/v1/chat/completions` Direct Execution

**Status:** Planned

### Problem / Goal

Make `POST /v1/chat/completions` execute directly against the runtime.

### Implementation Tasks

- [ ] Extract latest actionable user prompt from request
- [ ] decide whether this is a new or continuing conversation
- [ ] invoke runtime non-streaming path when `stream=false`
- [ ] invoke runtime streaming path when `stream=true`
- [ ] return OpenAI-shaped response payloads

### Acceptance Criteria

- [ ] non-streaming chat completions work end-to-end
- [ ] streaming chat completions work end-to-end
- [ ] assistant text matches runtime output

---

## 8. Workstream D — Model / Config Mapping

**Status:** Planned

### Problem / Goal

Map proxy model identifiers to local runtime session material.

### Implementation Tasks

- [ ] define initial static model aliases
- [ ] map model IDs to:
  - `transport_mode`
  - `thinking_mode`
  - `model_name`
- [ ] define safe defaults for omitted fields
- [ ] keep config explicit and documented

### Acceptance Criteria

- [ ] model IDs resolve deterministically
- [ ] runtime receives the intended transport/thinking/model values

---

## 9. Workstream E — Session Material Strategy

**Status:** Planned

### Problem / Goal

Decide how the proxy acquires auth/browser settings.

### Implementation Tasks

- [ ] define config source for cookies/auth/browser profile fields
- [ ] reuse existing session conventions from this repo where possible
- [ ] decide whether proxy is single-user or keyed multi-profile in Phase 2
- [ ] redact sensitive values in logs/debug output

### Acceptance Criteria

- [ ] proxy can start with usable runtime session material
- [ ] secrets are not printed raw

---

## 10. Workstream F — Direct Runtime Tests

**Status:** Planned

### Implementation Tasks

- [ ] mock transport construction tests
- [ ] chat completion response-shaping tests
- [ ] streaming conversion tests against runtime chunk inputs
- [ ] conversation reuse tests

### Acceptance Criteria

- [ ] runtime integration is covered without depending on live browser execution

---

## 11. Combined Implementation Order

1. Add runtime client wrapper
2. Add conversation state mapping
3. Implement direct `/v1/chat/completions`
4. Implement model/config mapping
5. Add session material strategy
6. Add tests
7. Run local end-to-end smoke checks

### Acceptance Criteria for First Combined Run

- [ ] one-shot non-streaming call works
- [ ] one-shot streaming call works
- [ ] continuing conversation works
- [ ] new conversation isolation works

---

## 12. Definition of Done

### 12.1 Runtime integration

- [ ] proxy directly uses local runtime code
- [ ] no `api_server.py` dependency exists in request execution path

### 12.2 Conversation handling

- [ ] new vs continuing conversation behavior is explicit
- [ ] state reuse is deterministic

### 12.3 Compatibility

- [ ] `/v1/chat/completions` works for both streaming and non-streaming clients

### 12.4 Testing

- [ ] direct runtime integration tests exist

---

## 13. What Phase 3 Inherits

Phase 3 inherits:

- a working direct-runtime OpenAI-compatible proxy
- basic model/config resolution
- in-memory conversation continuity

Phase 3 focuses on pi compatibility validation and higher-level agent usage.
