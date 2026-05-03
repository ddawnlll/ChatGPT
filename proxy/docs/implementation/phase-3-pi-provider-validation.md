# Phase 3 — pi Provider Validation and Agent-Facing Hardening

**Status:** Complete
**Owner:** Proxy/agent integration track
**Last updated:** 2026-05-03
**Delivery status:** Complete

---

## 1. Purpose

This phase validates the proxy as a usable provider for **pi coding agent** and hardens the compatibility layer for real agent workflows.

pi is the primary target. Roo Code and other OpenAI-compatible clients are secondary follow-on targets.

---

## 2. What Carried Over / What Must Stay Stable

- [x] Phase 1 HTTP compatibility shell
- [x] Phase 2 direct runtime integration
- [x] Playwright-first execution strategy
- [x] OpenAI-compatible `/v1/chat/completions` endpoint
- [x] `/v1/models` model list

---

## 3. Background & Motivation

A proxy is not finished when it merely returns valid JSON. It is finished when a real client can actually use it.

For this project, the first real client target is pi because:

- it supports custom OpenAI-compatible providers cleanly
- it has a straightforward model/provider config path
- it is the preferred agent target for this effort

---

## 4. Current Failure State / Known Blockers

Original blockers were:

- pi might not accept the returned provider/model surface cleanly
- message role compatibility might need adjustment
- streaming behavior might still need compatibility tuning
- model metadata might be incomplete for pi registration

These are resolved for the pi-first path.

---

## 5. Workstream A — pi Provider Compatibility Contract

**Status:** Complete

### Problem / Goal

Define the exact subset of OpenAI compatibility required by pi.

### Implementation Tasks

- [x] validate `openai-completions` behavior with pi
- [x] decide whether `openai-responses` is also needed
- [x] set compatibility expectations for:
  - `developer` role support
  - `reasoning_effort`
  - images/tool-call fields
- [x] document required `models.json` config

### Notes

Current pi path uses:

- `api: "openai-completions"`
- `compat.supportsDeveloperRole = false`
- `compat.supportsReasoningEffort = false`

`openai-responses` is not required for the first working pi integration.

### Acceptance Criteria

- [x] pi can enumerate and select the proxy model(s)
- [x] documented compat flags are sufficient

---

## 6. Workstream B — Real pi Smoke Tests

**Status:** Complete

### Implementation Tasks

- [x] create a local `~/.pi/agent/models.json` example for this proxy
- [x] run pi against the proxy in a real repo
- [x] verify non-streaming completion behavior
- [x] verify streaming behavior
- [x] verify multi-turn continuity

### Validation Results

Created:

- `proxy/examples/pi-models.json`
- `proxy/docs/implementation/pi-provider-setup.md`

Validated commands:

```bash
PI_CODING_AGENT_DIR=/tmp/pi-proxy-agent-dir pi --list-models chatgpt-wrapper
```

Result:

- `chatgpt-wrapper/chatgpt-playwright`
- `chatgpt-wrapper/chatgpt-authenticated`

Validated real prompt:

```bash
PI_CODING_AGENT_DIR=/tmp/pi-proxy-agent-dir \
pi --provider chatgpt-wrapper --model chatgpt-playwright --session-dir /tmp/pi-proxy-sessions -p "Remember token RIVERSTONE and reply only with ACK"
```

Observed result:

- `ACK`

Validated multi-turn continuation:

```bash
PI_CODING_AGENT_DIR=/tmp/pi-proxy-agent-dir \
pi --provider chatgpt-wrapper --model chatgpt-playwright --session-dir /tmp/pi-proxy-sessions --continue -p "What token did I tell you to remember? Reply with the token only."
```

Observed result:

- `RIVERSTONE`

### Acceptance Criteria

- [x] pi can send prompts successfully
- [x] pi can receive streamed responses successfully
- [x] multi-turn use is stable enough for coding sessions

---

## 7. Workstream C — Error/Edge Compatibility Hardening

**Status:** Complete

### Problem / Goal

Smooth out client-facing compatibility issues exposed by real pi usage.

### Implementation Tasks

- [x] normalize edge-case error payloads
- [x] ensure malformed upstream/runtime failures remain understandable to pi users
- [x] verify `[DONE]` termination and chunk ordering
- [x] tune response fields that pi expects but may ignore or mis-handle

### What was hardened

- added history-based conversation reuse for pi-style full-message-history requests
- kept OpenAI-style validation and runtime error payloads
- preserved streaming completion termination with `[DONE]`

### Acceptance Criteria

- [x] pi does not fail due to proxy formatting quirks
- [x] common proxy/runtime failures are legible

---

## 8. Workstream D — Documentation / Operator Guidance

**Status:** Complete

### Implementation Tasks

- [x] document how to run the proxy locally
- [x] document the exact pi provider config
- [x] document recommended model IDs
- [x] document known limitations (e.g. transport modes)

### Produced docs

- `proxy/docs/implementation/pi-provider-setup.md`
- `proxy/examples/pi-models.json`

### Acceptance Criteria

- [x] a developer can point pi at the proxy without guesswork

---

## 9. Workstream E — Secondary Client Readiness

**Status:** Complete

### Problem / Goal

Keep follow-on compatibility with Roo Code and similar clients possible without letting that complexity block pi.

### Implementation Tasks

- [x] note Roo-specific deltas separately
- [x] avoid hardcoding Roo-specific shims into the initial pi-first path unless required
- [x] document future compatibility work as follow-up tasks

### Notes

The current implementation remains pi-first and does not add Roo-specific behavior into the core request path.

### Acceptance Criteria

- [x] pi remains the primary contract
- [x] Roo work is tracked without derailing the core proxy

---

## 10. Combined Implementation Order

1. Define pi compatibility contract
2. Run real pi smoke tests
3. Fix formatting/streaming mismatches
4. Document setup and usage
5. Record secondary client follow-ups

### Acceptance Criteria for First Combined Run

- [x] pi can list the proxy model
- [x] pi can send a coding prompt
- [x] pi can receive a complete streamed answer
- [x] a second turn continues correctly

---

## 11. Definition of Done

### 11.1 pi compatibility

- [x] pi works with the proxy via custom provider config
- [x] model list / chat completion routes behave compatibly

### 11.2 Streaming

- [x] streamed deltas are accepted in real pi usage
- [x] final completion is complete and well-formed

### 11.3 Documentation

- [x] setup docs exist for pi integration
- [x] known limitations are documented

---

## 12. Phase Boundary

This phase makes the proxy practically usable for the intended coding agent workflow.

Follow-on work can now target:

- Roo Code compatibility
- Responses API depth
- persistence hardening
- multi-profile routing
- productionization
