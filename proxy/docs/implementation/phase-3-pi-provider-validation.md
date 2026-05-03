# Phase 3 — pi Provider Validation and Agent-Facing Hardening

**Status:** Planned
**Owner:** Proxy/agent integration track
**Last updated:** 2026-05-03
**Delivery status:** Not started

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

Before this phase:

- pi may not accept the returned provider/model surface cleanly
- message role compatibility may need adjustment
- streaming behavior may still need compatibility tuning
- model metadata may be incomplete for pi registration

---

## 5. Workstream A — pi Provider Compatibility Contract

**Status:** Planned

### Problem / Goal

Define the exact subset of OpenAI compatibility required by pi.

### Implementation Tasks

- [ ] validate `openai-completions` behavior with pi
- [ ] decide whether `openai-responses` is also needed
- [ ] set compatibility expectations for:
  - `developer` role support
  - `reasoning_effort`
  - images/tool-call fields
- [ ] document required `models.json` config

### Acceptance Criteria

- [ ] pi can enumerate and select the proxy model(s)
- [ ] documented compat flags are sufficient

---

## 6. Workstream B — Real pi Smoke Tests

**Status:** Planned

### Implementation Tasks

- [ ] create a local `~/.pi/agent/models.json` example for this proxy
- [ ] run pi against the proxy in a real repo
- [ ] verify non-streaming completion behavior
- [ ] verify streaming behavior
- [ ] verify multi-turn continuity

### Acceptance Criteria

- [ ] pi can send prompts successfully
- [ ] pi can receive streamed responses successfully
- [ ] multi-turn use is stable enough for coding sessions

---

## 7. Workstream C — Error/Edge Compatibility Hardening

**Status:** Planned

### Problem / Goal

Smooth out client-facing compatibility issues exposed by real pi usage.

### Implementation Tasks

- [ ] normalize edge-case error payloads
- [ ] ensure malformed upstream/runtime failures remain understandable to pi users
- [ ] verify `[DONE]` termination and chunk ordering
- [ ] tune response fields that pi expects but may ignore or mis-handle

### Acceptance Criteria

- [ ] pi does not fail due to proxy formatting quirks
- [ ] common proxy/runtime failures are legible

---

## 8. Workstream D — Documentation / Operator Guidance

**Status:** Planned

### Implementation Tasks

- [ ] document how to run the proxy locally
- [ ] document the exact pi provider config
- [ ] document recommended model IDs
- [ ] document known limitations (e.g. transport modes)

### Acceptance Criteria

- [ ] a developer can point pi at the proxy without guesswork

---

## 9. Workstream E — Secondary Client Readiness

**Status:** Planned

### Problem / Goal

Keep follow-on compatibility with Roo Code and similar clients possible without letting that complexity block pi.

### Implementation Tasks

- [ ] note Roo-specific deltas separately
- [ ] avoid hardcoding Roo-specific shims into the initial pi-first path unless required
- [ ] document future compatibility work as follow-up tasks

### Acceptance Criteria

- [ ] pi remains the primary contract
- [ ] Roo work is tracked without derailing the core proxy

---

## 10. Combined Implementation Order

1. Define pi compatibility contract
2. Run real pi smoke tests
3. Fix formatting/streaming mismatches
4. Document setup and usage
5. Record secondary client follow-ups

### Acceptance Criteria for First Combined Run

- [ ] pi can list the proxy model
- [ ] pi can send a coding prompt
- [ ] pi can receive a complete streamed answer
- [ ] a second turn continues correctly

---

## 11. Definition of Done

### 11.1 pi compatibility

- [ ] pi works with the proxy via custom provider config
- [ ] model list / chat completion routes behave compatibly

### 11.2 Streaming

- [ ] streamed deltas are accepted in real pi usage
- [ ] final completion is complete and well-formed

### 11.3 Documentation

- [ ] setup docs exist for pi integration
- [ ] known limitations are documented

---

## 12. Phase Boundary

This phase makes the proxy practically usable for the intended coding agent workflow.

After this phase, follow-on work can target:

- Roo Code compatibility
- Responses API depth
- persistence hardening
- multi-profile routing
- productionization
