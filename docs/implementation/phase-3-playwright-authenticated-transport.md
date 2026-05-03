# Phase 3 — Playwright-Backed Authenticated Transport

**Status:** In progress
**Owner:** API/runtime track
**Last updated:** 2026-05-03
**Delivery status:** Workstream A first pass complete; Workstream B initial scaffolding in progress

---

## 1. Purpose

This phase introduces a new authenticated transport that uses a real browser session through Playwright instead of continuing to emulate the private ChatGPT web protocol entirely from Python.

The goal is **not** to replace the existing app API.

The goal is:

- keep the current FastAPI + SQLite + React architecture,
- keep the current local chat persistence model,
- keep the current frontend streaming UX,
- keep anon/debug transport paths available,
- but make authenticated ChatGPT interaction run through a real browser profile/session,
- and use that browser as the primary authenticated execution engine.

The intended end state is:

- `transport_mode="playwright"` becomes the recommended authenticated mode,
- `transport_mode="authenticated"` remains available as a reverse-engineering / experimental Python-native path,
- `transport_mode="anon"` remains available as fallback/debug,
- the frontend and API continue to expose our own stable chat endpoints regardless of which transport is used internally.

---

## 2. Direction and Constraints

### Primary Direction

The system should continue to present **our own API** and **our own app-level chat model** while delegating authenticated ChatGPT execution to a real browser session controlled by Playwright.

That means:

- browser automation becomes the primary authenticated transport,
- our backend remains the source of truth for local chats/messages/settings,
- our frontend continues to stream from our backend rather than talking to ChatGPT directly,
- transport selection becomes an internal implementation detail behind our API.

### Explicit Constraints

This phase must **not**:

- [ ] remove the current FastAPI API surface
- [ ] remove SQLite persistence
- [ ] remove the current React chat UI
- [ ] bypass security, login, or anti-bot protections
- [ ] attempt to scrape credentials beyond what the user already has in their real browser profile/session
- [ ] pretend imported cookies alone are sufficient for authenticated browser-grade behavior
- [ ] silently rewrite existing local chats into a different persistence model
- [ ] block future Python-native authenticated transport research

### Expected Reality

The browser is the real ChatGPT client. For authenticated usage, trying to reproduce every hidden browser behavior from Python has already proven brittle.

This phase intentionally accepts a heavier runtime in exchange for:

- better alignment with real ChatGPT behavior,
- fewer challenge/session mismatches,
- simpler validation,
- and faster progress toward a usable system.

---

## 3. What Must Stay Stable

The following are already implemented and must remain stable through this phase:

- [x] FastAPI chat CRUD endpoints
- [x] SQLite persistence for local chats/messages
- [x] frontend chat flow and layout
- [x] backend SSE streaming endpoint shape
- [x] frontend optimistic/live rendering model
- [x] transport diagnostics / verification data model
- [x] anon transport path for fallback/debug

This phase must not regress the current ability to:

- create chats
- select chats
- rename/delete chats
- send messages
- stream assistant output live to the frontend
- persist local app state
- inspect transport diagnostics

---

## 4. Why We Are Pivoting

The Python-native authenticated transport reached meaningful discovery progress but is still blocked or destabilized by browser-only behavior.

Observed issues:

- imported cookies can make the UI appear logged in but do **not** reliably reproduce authenticated backend send behavior,
- browser automation with cookie import hit `403` / HTML challenge on `POST /backend-api/f/conversation/prepare`,
- the authenticated flow requires post-handoff websocket continuation,
- websocket URL / verify state is browser-derived and not always present in exported HARs,
- browser state clearly includes more than a static cookie jar.

Conclusion:

- Playwright-only discovery is useful,
- but Python-native transport still carries most of the private-protocol risk,
- so the best practical next step is to move authenticated execution into the browser itself.

---

## 5. Phase Goal

By the end of this phase, the system should:

- support `transport_mode="playwright"`,
- send authenticated messages through a real Chromium/Chrome profile,
- stream assistant output back through our backend SSE endpoint,
- preserve local chat persistence and frontend behavior,
- expose clear diagnostics when real-profile browser automation still encounters challenge/login blockers,
- and make Playwright the recommended authenticated runtime path for practical usage.

---

## 6. Architecture Target

### External contract stays the same

The frontend should continue calling our API, e.g.:

- `POST /chats`
- `GET /chats`
- `GET /chats/{chat_id}`
- `POST /chats/{chat_id}/messages`
- `POST /chats/{chat_id}/messages/stream`

### Internal transport changes

The backend transport layer should become pluggable:

- `anon`
- `authenticated` (current Python-native experimental path)
- `playwright` (new primary authenticated path)

### Runtime ownership split

**Our backend owns:**
- local chat IDs
- local messages
- persistence
- settings/session config
- SSE to frontend
- verification metadata
- transport diagnostics

**Playwright transport owns:**
- real browser profile/session usage
- opening ChatGPT
- sending prompts through the real web client
- observing browser/network/websocket/DOM response flow
- extracting assistant output and remote conversation metadata

---

## 7. Workstream A — Transport Boundary Refactor

**Status:** First pass complete

### Problem / Goal

Authenticated runtime logic is currently centered around `wrapper/chatgpt.py`. We need a clean abstraction so the backend can choose between Python-native and Playwright-backed transports without duplicating API behavior.

### Implementation Tasks

- [ ] define an internal transport interface for send/stream operations
- [ ] isolate API-server-facing transport calls from wrapper-specific implementation details
- [ ] ensure transport result shape is normalized across implementations
- [ ] preserve diagnostics hooks so frontend debug panels remain useful

### Candidate Result Shape

Each transport should produce a normalized result such as:

- `text`
- `remote_conversation_id`
- `remote_parent_message_id`
- `chunks` / streaming iterator
- `transport_details`
- `verification_hints`

### Acceptance Criteria

- [x] API endpoints do not need transport-specific branching everywhere
- [x] transport selection is centralized
- [x] adding `playwright` does not break `anon` or current `authenticated`

### Implementation Notes

Completed first pass:

- added `transport_runtime.py`
- introduced `TransportResult`
- introduced `ChatTransport` protocol
- wrapped the existing wrapper client in `ChatGPTTransport`
- refactored `api_server.py` to call transport adapter methods instead of wrapper methods directly

This creates the seam required for a future `PlaywrightTransport` without forcing another API-server rewrite.

---

## 8. Workstream B — Playwright Runner / Worker

**Status:** In progress

### Problem / Goal

We need a dedicated Playwright-based runtime that can use a real browser profile and act as the authenticated ChatGPT client.

### Implementation Tasks

- [ ] create a browser transport runner, likely under `tools/` or a dedicated transport module
- [ ] support launching Chromium/Chrome with:
  - `--user-data-dir`
  - `--profile-directory`
  - optional `--executable-path`
- [ ] explicitly prefer real profile mode over cookie-import mode
- [ ] navigate to ChatGPT and validate that UI looks authenticated
- [ ] send a prompt using the real composer
- [ ] observe response generation through DOM and/or network/websocket events
- [ ] emit structured progress/events that Python can consume

### Important Constraints

- [ ] do not automate login beyond using a profile the user already controls
- [ ] do not bypass challenges
- [ ] if the browser profile still hits a blocker, surface it loudly as diagnostics

### Acceptance Criteria

- [ ] the runner can send a prompt from a real profile
- [x] the runner can return assistant text in a normalized event format when browser execution succeeds
- [x] the runner can expose enough detail for debugging challenge/login failures

### Implementation Notes

Initial scaffolding completed:

- added `tools/playwright_chat_transport.mjs`
- runner accepts JSON on stdin and emits JSONL events on stdout
- emits:
  - `status`
  - `chunk`
  - `result`
- added Python-side `PlaywrightTransport` adapter in `transport_runtime.py`
- added `transport_mode="playwright"` to API-side transport normalization/session plumbing
- added CDP attach mode so Playwright can attach to a running debug-enabled Chromium instance instead of always relaunching the profile
- added optional auto-start support for a debug-enabled Chromium launch with remote debugging port

Current limitation:

- the first Playwright runner is still DOM-driven and intended as a functional scaffold, not yet the final robust selector/network hybrid.
- even with CDP attach support, successful real-profile validation still depends on browser/challenge behavior in the live environment.
- because full browser-driven response extraction is still brittle, Playwright session extraction/discovery remains an important fallback path for feeding richer session material back into the Python-native authenticated transport.

---

## 9. Workstream C — Streaming Strategy

**Status:** Planned

### Problem / Goal

The frontend already expects live SSE from our backend. The Playwright transport must produce chunked output in a way that integrates with the existing UI.

### Implementation Options

We may combine both:

1. **DOM-driven streaming**
   - watch the assistant message node as text appears
   - simpler fallback

2. **Network/websocket-driven streaming**
   - observe websocket frames / network events where feasible
   - closer to protocol truth
   - potentially more structured

### Initial Direction

Start with the most reliable implementation that can produce incremental chunks safely.

That likely means:

- DOM-first for fast practicality,
- network/websocket diagnostics in parallel,
- promote lower-level streaming extraction only if it improves reliability.

### Acceptance Criteria

- [ ] backend SSE still streams assistant text live
- [ ] frontend UX remains close to current streaming behavior
- [ ] chunk duplication / race issues are handled

---

## 10. Workstream D — Remote Conversation Continuity

**Status:** Planned

### Problem / Goal

Authenticated usage is most valuable if follow-ups stay attached to the same real remote ChatGPT conversation.

### Implementation Tasks

- [ ] capture remote conversation URL / ID when a chat is created or continued
- [ ] decide how to reopen or continue the same remote conversation in Playwright
- [ ] persist any required remote identifiers in local chat metadata
- [ ] confirm follow-up prompts remain linked correctly

### Key Question

Will continuation be best driven by:

- reopening the remote conversation URL, or
- staying in a long-lived browser page/context per local chat/session?

We should choose based on reliability and operational simplicity.

### Acceptance Criteria

- [ ] local chat follow-ups continue the same remote browser conversation when expected
- [ ] diagnostics clearly show remote conversation continuity state

---

## 11. Workstream E — API Server Integration

**Status:** Planned

### Problem / Goal

The backend must expose Playwright transport without changing the frontend contract.

### Implementation Tasks

- [ ] add `playwright` to accepted `transport_mode` values in request/session models
- [ ] allow Playwright-specific session config fields, e.g.:
  - `browser_executable_path`
  - `browser_user_data_dir`
  - `browser_profile_directory`
  - optional `browser_channel`
- [ ] route authenticated send/stream requests through Playwright transport when selected
- [ ] persist transport selection and diagnostics in chat detail responses
- [ ] preserve current SSE framing to frontend

### Acceptance Criteria

- [ ] frontend can choose Playwright mode without API shape breakage
- [ ] existing non-Playwright chats still load and function
- [ ] transport diagnostics are visible in `GET /chats/{chat_id}` and debug endpoints

---

## 12. Workstream F — Frontend Settings and Diagnostics

**Status:** Planned

### Problem / Goal

Users need an explicit way to configure and inspect Playwright transport behavior.

### Implementation Tasks

- [ ] add `playwright` to transport selection UI
- [ ] add fields for:
  - executable path
  - user data dir
  - profile directory
  - optional headless toggle if we decide to support it
- [ ] label cookie-import mode as fallback/debug only
- [ ] surface blocker diagnostics such as:
  - profile missing
  - UI not logged in
  - `prepare` 403/challenge
  - no websocket/handoff reached

### Acceptance Criteria

- [ ] frontend makes Playwright configuration understandable
- [ ] users can see why authenticated send failed without reading raw logs

---

## 13. Workstream G — Manual Debugger Pivot

**Status:** In progress

### Problem / Goal

`manual_authenticated.py` currently focuses on the Python-native authenticated transport. We need a manual debugger path that matches the new recommended runtime.

### Implementation Tasks

- [ ] add a Playwright-backed manual mode or a dedicated manual runner
- [ ] support real browser profile parameters
- [ ] print clear state for:
  - profile selection
  - UI login detection
  - send attempt
  - streamed output
  - blockers/challenges
- [ ] keep the existing Python-native authenticated debugger available for research mode

### Acceptance Criteria

- [x] we can validate Playwright transport independently of the frontend at the transport-adapter/manual-runner boundary
- [x] the manual tool can select Playwright mode and print browser profile configuration/transport diagnostics

### Implementation Notes

Initial manual-tool pivot completed:

- `manual_authenticated.py` now respects `session.json.transport_mode`
- when `transport_mode="playwright"`, it builds the browser-backed transport instead of the Python-native authenticated wrapper path
- it prints selected browser profile fields for debugging
- non-Playwright mode continues to support the earlier authenticated websocket-discovery workflow

Current limitation:

- full real-profile validation still depends on running the Playwright manual path against an actual working browser profile.

---

## 14. Workstream H — Verification Against Real ChatGPT Behavior

**Status:** Planned

### Problem / Goal

We still need to confirm that Playwright mode behaves like real ChatGPT in the ways users care about.

### Verification Targets

- [ ] messages appear in the actual ChatGPT conversation UI
- [ ] follow-ups remain attached to the same remote conversation
- [ ] sidebar/history reflects expected account behavior when applicable
- [ ] titles/conversation naming behavior is understood
- [ ] local app state remains consistent with visible browser state

### Acceptance Criteria

- [ ] we have a verified happy-path run with a real profile
- [ ] we know which behaviors are guaranteed vs best-effort

---

## 15. File-Level Impact Forecast

### Likely major rewrites / substantial changes

- `manual_authenticated.py`
- `api_server.py`
- authenticated sections of `wrapper/chatgpt.py`
- new Playwright transport runner/module

### Likely moderate changes

- `frontend/src/ui/chat-shell.tsx`
- `frontend/src/lib/api.ts`
- `session.example.json`
- tests around authenticated/manual flows

### Likely mostly stable

- chat persistence model
- chat CRUD endpoints
- frontend routing/layout structure
- anon transport implementation

---

## 16. Risks

### Known Risks

- browser automation is heavier than pure HTTP transport
- selector drift in ChatGPT UI can break prompt/response extraction
- real browser profile paths differ across systems
- some browser profiles may still hit challenge/login blockers
- concurrency may be harder with browser-backed sessions than HTTP-backed sessions

### Mitigations

- keep diagnostics first-class
- keep `anon` and Python-native authenticated modes available
- prefer explicit real-profile configuration over guessing
- start with single-session/manual correctness before scaling concurrency

---

## 17. Acceptance Criteria for the Phase

This phase is complete when:

- [ ] `transport_mode="playwright"` exists and is wired end-to-end
- [ ] a real Chromium/Chrome profile can be used to send at least one authenticated message successfully
- [ ] backend SSE streams that message live to the frontend
- [ ] local chat persistence remains functional
- [ ] failure diagnostics clearly distinguish:
  - missing profile
  - not logged in
  - challenge/403 blocker
  - transport/runtime failure after send
- [ ] the frontend and API remain our own stable contract even though the authenticated transport is browser-backed

---

## 18. Recommended Execution Order

1. **Transport boundary refactor**
2. **Playwright runner with real-profile support**
3. **manual Playwright validation path**
4. **API server integration**
5. **backend SSE streaming integration**
6. **frontend settings / diagnostics updates**
7. **real-profile verification against ChatGPT behavior**
8. **optional cleanup / downgrade of Python-native authenticated path from primary to experimental**

---

## 19. Summary

Phase 3 keeps the app architecture we already built, but stops treating Python-native authenticated protocol emulation as the main path to success.

Instead:

- our app API remains stable,
- our local persistence remains stable,
- our frontend remains stable,
- and authenticated execution moves into the real browser client through Playwright.

This is heavier, but it is currently the most practical route to a stable authenticated system.
