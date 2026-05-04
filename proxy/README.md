# ChatGPT OpenAI-Compatible Proxy

**Status:** Planning / scaffolding
**Primary target agent:** pi
**Secondary target agent:** Roo Code / other OpenAI-compatible clients

---

## Purpose

This directory will contain an OpenAI-compatible proxy that sits directly on top of this repository's ChatGPT runtime.

The proxy will:

- expose OpenAI-compatible endpoints such as:
  - `POST /v1/chat/completions`
  - `POST /v1/responses` (optional in early phases, recommended)
  - `GET /v1/models`
  - `GET /health`
- call the local runtime directly via:
  - `transport_runtime.py`
  - `wrapper/chatgpt.py`
- support the project's preferred transport modes:
  - `playwright` as the practical primary mode
  - `authenticated` as experimental / secondary
  - `anon` only for debug / fallback
- be usable by coding agents, especially **pi**, through a standard OpenAI-compatible provider surface

This proxy is **not** meant to call `api_server.py` as an intermediate HTTP backend. It should use the Python runtime in-process.

---

## Why this exists

The repository already has:

- a working ChatGPT web-wrapper runtime
- transport abstraction in `transport_runtime.py`
- Playwright-backed browser execution
- local chat/thread state concepts
- streaming support

What it does not yet have is a clean OpenAI-compatible compatibility layer for external agents.

The goal of `proxy/` is to provide that layer without duplicating the fragile browser transport logic.

---

## Architecture target

```text
pi / Roo / OpenAI-compatible client
        │
        ▼
proxy/  (FastAPI, OpenAI-compatible surface)
        │
        ▼
transport_runtime.py
        │
        ├── PlaywrightTransport
        └── ChatGPTTransport
                │
                ▼
wrapper/chatgpt.py / browser transport
```

---

## Design principles

1. **Direct runtime integration**
   - The proxy should import and use local Python runtime code directly.
   - It should not proxy through `api_server.py`.

2. **OpenAI-compatible on the outside**
   - The external API should look standard enough for pi and other clients.

3. **Do not reimplement transport logic in the proxy**
   - Keep Playwright/session/web-wrapper complexity in `transport_runtime.py` and `wrapper/chatgpt.py`.

4. **pi-first compatibility**
   - The first-class integration target is pi via `openai-completions` and/or `openai-responses`.

5. **Stateful conversation mapping inside the proxy**
   - Because OpenAI-style clients are often request-oriented, the proxy must manage conversation/runtime state itself.

---

## Initial scope

### In scope

- OpenAI-compatible HTTP interface
- direct runtime usage through `build_transport(...)`
- streaming conversion to OpenAI SSE format
- simple in-memory conversation/session store
- model list endpoint suitable for pi
- health endpoint
- error normalization

### Out of scope for first phase

- full persistence parity with `api_server.py`
- complex multi-user tenancy
- OAuth/login UX in the proxy itself
- browser profile management UI
- reproducing every Roo-specific shim immediately

---

## Planned layout

```text
proxy/
├── README.md
├── docs/
│   └── implementation/
│       ├── phase-1-openai-compatible-proxy-foundation.md
│       ├── phase-2-direct-chatgpt-runtime-integration.md
│       ├── phase-3-pi-provider-validation.md
│       └── reuse-from-perplexity-proxy.md
└── app/
    ├── main.py
    ├── config.py
    ├── models.py
    ├── client.py
    ├── router.py
    ├── state.py
    └── streaming.py
```

---

## Main source dependencies in this repo

The proxy is expected to build on:

- `transport_runtime.py`
- `wrapper/chatgpt.py`
- `manual_authenticated.py` (config conventions / debug conventions)
- `tools/playwright_chat_transport.mjs` (indirectly via transport runtime)

Reference implementation patterns are available in:

- `perplexity-proxy/app/main.py`
- `perplexity-proxy/app/models.py`
- `perplexity-proxy/app/streaming.py`
- `perplexity-proxy/app/router.py`
- `perplexity-proxy/tests/`

---

## Recommended implementation order

1. Build the HTTP shell and OpenAI-shaped schemas
2. Add direct runtime client wrapper over `build_transport(...)`
3. Add in-memory conversation state mapping
4. Implement `/v1/chat/completions`
5. Implement streaming SSE conversion
6. Implement `/v1/models` for pi
7. Validate with pi via `models.json`
8. Add `/v1/responses` if needed for better compatibility

---

## pi integration target

Once the proxy works, pi should be able to use it with a custom provider config similar to:

```json
{
  "providers": {
    "chatgpt-wrapper": {
      "baseUrl": "http://127.0.0.1:8080/v1",
      "api": "openai-completions",
      "apiKey": "dummy",
      "compat": {
        "supportsDeveloperRole": false,
        "supportsReasoningEffort": false
      },
      "models": [
        {
          "id": "chatgpt-playwright",
          "name": "ChatGPT Playwright",
          "reasoning": true,
          "input": ["text"],
          "contextWindow": 128000,
          "maxTokens": 16384,
          "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 }
        }
      ]
    }
  }
}
```

---

## Documentation map

- `proxy/docs/implementation/phase-1-openai-compatible-proxy-foundation.md`
- `proxy/docs/implementation/phase-2-direct-chatgpt-runtime-integration.md`
- `proxy/docs/implementation/phase-3-pi-provider-validation.md`
- `proxy/docs/implementation/pi-provider-setup.md`
- `proxy/docs/implementation/reuse-from-perplexity-proxy.md`

These docs define the plan, reuse inventory, and implementation boundaries.

---

## Testing

The proxy now has tiered automated tests so CI does not depend on live ChatGPT for every run.

### Fast CI-safe tests

Run all fast tests:

```bash
make test-all-fast
```

Or run specific tiers:

```bash
make test-proxy
make test-pi-contract
make test-js
```

These cover:

- parser regressions in `proxy/app/tools_shim.py`
- router and SSE regressions for pi-agent-compatible requests
- mocked pi tool contract tests for `read`, `write`, `edit`, `bash`, `grep`, `find`, `ls`
- real pi CLI integration tests for `read`, `write`, `edit`, `bash`, `grep`, `find`, `ls`
- fake Playwright daemon protocol tests
- JS helper tests for `tools/playwright_chat_transport.mjs`

### Optional real-browser smoke tests

Real browser tests are marked with the `browser_e2e` pytest marker and are skipped by default.

Run them manually with:

```bash
RUN_BROWSER_E2E=1 make test-browser-e2e
```

These tests validate the live Playwright/browser path end-to-end and are intended for nightly or manual verification, not normal fast CI.

### CI workflows

- `.github/workflows/ci.yml`
  - installs Python and Bun dependencies
  - runs `make test-js`
  - runs `make test-all-fast`
- `.github/workflows/browser-nightly.yml`
  - manual/scheduled browser smoke workflow
  - guarded by `CHATGPT_PROXY_BROWSER_E2E_ENABLED=1`
