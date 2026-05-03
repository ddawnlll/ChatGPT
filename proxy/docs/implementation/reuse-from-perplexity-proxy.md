# Reuse Plan — Adapting `perplexity-proxy/` for the ChatGPT Runtime Proxy

**Status:** Planning reference
**Last updated:** 2026-05-03

---

## 1. Purpose

This document identifies which parts of `perplexity-proxy/` should be reused for `proxy/`, which parts must be edited, and which parts should not be carried over.

The goal is to reuse architecture and compatibility patterns without importing Perplexity-specific assumptions into the new proxy.

---

## 2. Reuse Strategy Summary

### Reuse mostly as patterns / templates

- `perplexity-proxy/app/main.py`
- `perplexity-proxy/app/models.py`
- `perplexity-proxy/app/streaming.py`
- route/test structure from `perplexity-proxy/tests/`

### Reuse selectively with major edits

- `perplexity-proxy/app/router.py`
- `perplexity-proxy/app/config.py`
- `perplexity-proxy/app/state.py`

### Do not reuse directly

- `perplexity-proxy/app/client.py`
- `perplexity-proxy/app/mapper.py`
- Perplexity tool shim logic in `app/tools/shim.py`
- Perplexity-specific caching/follow-up assumptions where they depend on upstream semantics

---

## 3. File-by-File Reuse Inventory

## 3.1 `perplexity-proxy/app/main.py`

**Reuse level:** High

### Reuse

- FastAPI app factory structure
- lifespan pattern
- logging setup
- API-key middleware pattern
- exception handler structure
- docs/openapi configuration

### Must edit

- rename branding / titles from Perplexity to ChatGPT proxy
- remove `init_client()` / `check_perplexity_session()` startup logic
- replace Perplexity settings references
- point startup health to local runtime/proxy state instead

### Do not carry over unchanged

- imports from `perplexity.models`
- Perplexity auth-health startup checks

---

## 3.2 `perplexity-proxy/app/models.py`

**Reuse level:** High

### Reuse

- request/response model shapes for:
  - chat completions
  - streaming chunks
  - responses API
  - model list
  - health response
- `extra="ignore"` style for compatibility

### Must edit

- trim any fields not needed initially
- add/adjust metadata fields for local runtime config if needed internally
- ensure naming and defaults match intended proxy behavior

### Notes

This file is one of the best direct skeleton sources.

---

## 3.3 `perplexity-proxy/app/streaming.py`

**Reuse level:** High

### Reuse

- OpenAI SSE formatting helpers
- `[DONE]` termination pattern
- chat completion chunk shape
- responses stream event shape
- delta emission structure

### Must edit

- replace Perplexity-specific chunk extraction logic
- replace `_extract_text(...)` and `_is_internal_chunk(...)` assumptions
- adapt input to local runtime stream chunks from `transport_runtime.py`

### Notes

Use this as a formatter template, not as-is logic.

---

## 3.4 `perplexity-proxy/app/router.py`

**Reuse level:** Medium

### Reuse

- route layout
- separation between route layer and client layer
- health/models/chat-completions/responses endpoint grouping
- response-shaping structure
- logging summary helpers pattern

### Must edit heavily

- remove Perplexity `search(...)` calls
- remove Perplexity follow-up store semantics
- replace message extraction logic only where still useful
- replace model resolution flow
- replace tool shim assumptions
- attach routes to direct local runtime client wrapper

### Sections most likely reusable with edits

- basic request parsing helpers
- prompt extraction helpers
- response model assembly
- streaming route structure

### Sections likely to remove entirely

- Perplexity tool shim integration
- Perplexity-specific follow-up handling
- any Perplexity-only citation/content cleanup assumptions

---

## 3.5 `perplexity-proxy/app/client.py`

**Reuse level:** Low

### Do not reuse directly

This file is tightly coupled to:

- `perplexity_async.Client`
- Perplexity exception types
- Perplexity cookie/session checks
- `client.search(...)`

### Replacement target

Create a fresh `proxy/app/client.py` that:

- wraps `build_transport(...)`
- manages per-conversation runtime state
- exposes direct send/stream methods
- normalizes runtime exceptions into HTTP-facing errors

---

## 3.6 `perplexity-proxy/app/config.py`

**Reuse level:** Medium

### Reuse

- `BaseSettings` pattern
- YAML/env layering pattern
- simple config object structure

### Must edit

- replace `PERPLEXITY_COOKIES` with ChatGPT runtime/browser/session fields
- define proxy-local defaults for:
  - `transport_mode`
  - browser profile paths
  - CDP URL
  - API-key auth
- remove Perplexity naming everywhere

---

## 3.7 `perplexity-proxy/app/mapper.py`

**Reuse level:** Low

### Do not reuse directly

This file depends on dynamic Perplexity model registry behavior.

### Replacement target

Use a simple static model registry first, mapping proxy model IDs to local runtime config:

- `transport_mode`
- `thinking_mode`
- `model_name`

---

## 3.8 `perplexity-proxy/app/state.py`

**Reuse level:** Medium

### Reuse

- general idea of in-memory state store

### Must edit

- replace Perplexity follow-up / response ID semantics with proxy-local conversation mapping
- track local runtime client/transport reuse
- track remote conversation IDs from ChatGPT runtime when needed

---

## 3.9 `perplexity-proxy/app/cache.py`

**Reuse level:** Optional / low in Phase 1

### Recommendation

Do not prioritize carrying this over initially.

Caching is not core to getting a correct agent-facing proxy working. It can be revisited later.

---

## 3.10 `perplexity-proxy/app/tools/shim.py`

**Reuse level:** Very low

### Recommendation

Do not bring this into initial proxy work.

This shim layer is tied to Perplexity/Roo-oriented behavior and would add complexity too early.

If pi-first compatibility works with a simpler OpenAI-compatible path, keep it simple.

---

## 3.11 Tests in `perplexity-proxy/tests/`

**Reuse level:** High as patterns

### Reuse

- route test structure
- streaming test structure
- health/models endpoint tests
- OpenAI-format assertion style

### Must edit

- replace Perplexity mocks with local runtime mocks
- replace model registry assumptions
- replace Perplexity-specific streaming chunk fixtures

---

## 4. Recommended New Files in `proxy/app/`

Create these files fresh, borrowing structure where useful:

- `proxy/app/main.py`
- `proxy/app/models.py`
- `proxy/app/streaming.py`
- `proxy/app/router.py`
- `proxy/app/client.py`
- `proxy/app/config.py`
- `proxy/app/state.py`

---

## 5. Recommended Copy/Edit Order

1. Copy/adapt `app/models.py`
2. Copy/adapt `app/main.py`
3. Copy/adapt `app/streaming.py`
4. Create fresh `app/client.py`
5. Create fresh `app/state.py`
6. Adapt `app/router.py`
7. Port tests by behavior, not by blind file copy

---

## 6. Explicit Non-Goals for Reuse

- Do not preserve Perplexity naming in public docs or code
- Do not preserve Perplexity-specific model mapping logic
- Do not preserve Perplexity-specific upstream parsing logic
- Do not preserve Roo-specific shims unless later proven necessary
- Do not depend on `api_server.py` as intermediary transport

---

## 7. Compact Mental Model

Use `perplexity-proxy/` as a **compatibility-shell reference**, not as an upstream client reference.

### Reuse directly-ish

- shell
- schemas
- SSE shape
- tests structure

### Rebuild for this repo

- runtime client
- state management
- model mapping
- upstream execution path

That split is the safest way to move quickly without importing the wrong assumptions.
