# Phase 1 — OpenAI-Compatible Proxy Foundation

**Status:** Complete
**Owner:** Proxy/runtime integration track
**Last updated:** 2026-05-03
**Delivery status:** Complete

---

## 1. Purpose

This phase creates the minimum standalone proxy foundation needed to expose this repository's ChatGPT runtime through an OpenAI-compatible HTTP surface.

This phase is about the HTTP shell, schemas, routing surface, health/error behavior, and baseline streaming shape.

It is not yet about deep conversation reuse, pi validation, or advanced provider quirks.

---

## 2. What Carried Over / What Must Stay Stable

The following already exist outside `proxy/` and must remain the source of truth:

- [x] `transport_runtime.py` transport abstraction
- [x] `PlaywrightTransport` as the practical primary path
- [x] `wrapper/chatgpt.py` conversation/runtime behavior
- [x] `tools/playwright_chat_transport.mjs` browser-side execution
- [x] existing session material conventions used by `manual_authenticated.py`

This phase must not duplicate or fork transport logic.

---

## 3. Background & Motivation

The repo currently has a working runtime and a local app server, but it does not yet expose a clean OpenAI-compatible interface for external coding agents.

The cloned `perplexity-proxy/` project provides a strong architectural template:

- FastAPI shell
- OpenAI-shaped schemas
- SSE formatting
- API-key middleware
- route/test structure

However, that project is Perplexity-specific. This phase extracts the reusable compatibility shell and adapts it for this ChatGPT runtime.

---

## 4. Current Failure State / Known Blockers

Initial Phase 1 blockers were:

- there was no `proxy/app/` implementation yet
- there was no OpenAI-compatible route surface in this repo dedicated to external agents
- there was no in-proxy request model for `chat/completions` or `responses`
- there was no proxy-local health or `/v1/models` endpoint
- there was no OpenAI SSE conversion helper

These are resolved for the foundation phase.

---

## 5. Workstream A — Proxy App Skeleton

**Status:** Complete

### Problem / Goal

Create the minimum application structure under `proxy/` using the reusable shell patterns from `perplexity-proxy/`.

### Implementation Tasks

- [x] Create `proxy/app/__init__.py`
- [x] Create `proxy/app/main.py`
- [x] Create `proxy/app/router.py`
- [x] Create `proxy/app/models.py`
- [x] Create `proxy/app/config.py`
- [x] Create `proxy/app/streaming.py`
- [x] Create `proxy/app/state.py`
- [x] Create `proxy/app/client.py`

### Acceptance Criteria

- [x] `proxy/` contains a coherent FastAPI app structure
- [x] app can start without importing Perplexity-specific code
- [x] route registration is separated from runtime client logic

---

## 6. Workstream B — OpenAI-Compatible Request/Response Schemas

**Status:** Complete

### Problem / Goal

Define the minimum Pydantic schema layer necessary for OpenAI-compatible clients.

### Implementation Tasks

- [x] Add `ChatRequest`, `ChatResponse`, streaming chunk models
- [x] Add `ModelList` / `ModelObject`
- [x] Add `HealthResponse`
- [x] Optionally add `ResponsesRequest` / `ResponsesResponse` placeholders now
- [x] Keep `extra="ignore"` behavior where helpful for compatibility

### Acceptance Criteria

- [x] `/v1/chat/completions` can validate standard request bodies
- [x] response models match expected OpenAI-compatible structure
- [x] initial schemas are sufficient for pi usage

---

## 7. Workstream C — Error and Health Surface

**Status:** Complete

### Problem / Goal

Make the proxy behave like a proper compatibility server with predictable health and error formatting.

### Implementation Tasks

- [x] Add `/health`
- [x] Add OpenAI-style error response helper
- [x] Add exception handlers for validation/runtime failures
- [x] Add optional API-key middleware scaffold
- [x] Add request logging middleware scaffold

### Acceptance Criteria

- [x] proxy returns health payload cleanly
- [x] validation errors are normalized
- [x] runtime errors do not leak raw stack traces by default

---

## 8. Workstream D — Baseline Streaming Formatter

**Status:** Complete

### Problem / Goal

Convert local runtime output into OpenAI-compatible SSE chunks.

### Implementation Tasks

- [x] Reuse the shape/pattern of `perplexity-proxy/app/streaming.py`
- [x] Implement `chat_completions_stream(...)`
- [x] Emit `data: {json}\n\n` chunks
- [x] Emit terminal `data: [DONE]\n\n`
- [x] Support cumulative-text to delta conversion if needed

### Acceptance Criteria

- [x] streaming route can produce valid OpenAI chat completion chunks
- [x] terminal `[DONE]` is emitted
- [x] chunk payloads are client-compatible

---

## 9. Workstream E — `/v1/models` Minimal Surface

**Status:** Complete

### Problem / Goal

Expose a static or near-static model list good enough for pi provider registration.

### Implementation Tasks

- [x] Add a small static model registry for first implementation
- [x] Include at least one Playwright-backed model entry
- [x] Include reasoning/input/context metadata required by clients
- [x] Keep model mapping simple and explicit in Phase 1

### Acceptance Criteria

- [x] `/v1/models` returns a valid list payload
- [x] returned models are enough to configure pi

---

## 10. Workstream F — Test Scaffold

**Status:** Complete

### Implementation Tasks

- [x] Add route tests for `/health`
- [x] Add route tests for `/v1/models`
- [x] Add request validation tests for `/v1/chat/completions`
- [x] Add streaming formatter tests for `[DONE]` termination
- [x] Add API-key middleware tests

### Acceptance Criteria

- [x] minimal proxy shell is test-backed
- [x] streaming shape is covered

### Validation Results

- [x] `python3 -m py_compile proxy/app/*.py proxy/tests/*.py`
- [x] `.venv-test/bin/pytest -q proxy/tests/test_proxy_phase1.py`
- [x] Current result: `9 passed`

---

## 11. Combined Implementation Order

1. Create app skeleton
2. Add schemas
3. Add health/errors/middleware
4. Add baseline streaming formatter
5. Add `/v1/models`
6. Add tests
7. Verify startup

### Acceptance Criteria for First Combined Run

- [x] proxy starts
- [x] `/health` works
- [x] `/v1/models` works
- [x] `/v1/chat/completions` request validation works
- [x] streaming formatter can emit valid OpenAI SSE

---

## 12. Definition of Done

### 12.1 App shell

- [x] `proxy/app/` exists with coherent module boundaries
- [x] no Perplexity-only imports remain in the shell

### 12.2 Compatibility surface

- [x] `/health` exists
- [x] `/v1/models` exists
- [x] `/v1/chat/completions` schema layer exists

### 12.3 Streaming

- [x] OpenAI-compatible SSE helper exists
- [x] `[DONE]` termination is correct

### 12.4 Testing

- [x] shell and streaming tests exist

---

## 13. What Phase 2 Inherits

Phase 2 inherits:

- a standalone FastAPI compatibility shell
- validated OpenAI-shaped schemas
- reusable SSE formatting helpers
- a model listing endpoint ready for client integration
- API-key and request-logging middleware scaffolding
- a placeholder runtime client boundary ready to be wired into `build_transport(...)`

Phase 2 then attaches these to the direct ChatGPT runtime.
