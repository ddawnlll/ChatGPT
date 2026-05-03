# pi Provider Setup for the ChatGPT Proxy

**Status:** Working setup reference
**Last updated:** 2026-05-03

---

## 1. Purpose

This document shows the exact setup used to point **pi** at the local ChatGPT proxy.

The proxy is intended to be used as an OpenAI-compatible provider with:

- `api: "openai-completions"`
- provider-level compatibility flags for developer-role and reasoning-effort quirks

---

## 2. Example `models.json`

Use:

- `proxy/examples/pi-models.json`

or copy its contents into:

- `~/.pi/agent/models.json`

The most important settings are:

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
      }
    }
  }
}
```

### Why these compat flags are set

- `supportsDeveloperRole: false`
  - pi will avoid provider behavior that assumes full `developer` role support.
- `supportsReasoningEffort: false`
  - pi will avoid sending `reasoning_effort` fields that this proxy does not currently interpret.

---

## 3. Starting the proxy

Example:

```bash
source /home/erfolg/src/gpt-fork/.venv/bin/activate
python -m uvicorn proxy.app.main:app --host 127.0.0.1 --port 8080
```

---

## 4. Pointing pi at a temporary agent directory

To test without touching your default pi config:

```bash
mkdir -p /tmp/pi-proxy-agent-dir
cp /home/erfolg/src/gpt-fork/proxy/examples/pi-models.json /tmp/pi-proxy-agent-dir/models.json
PI_CODING_AGENT_DIR=/tmp/pi-proxy-agent-dir pi --list-models chatgpt-wrapper
```

---

## 5. Example smoke command

```bash
PI_CODING_AGENT_DIR=/tmp/pi-proxy-agent-dir \
pi --provider chatgpt-wrapper --model chatgpt-playwright --no-session -p "Reply exactly: PI_PROXY_SMOKE_OK"
```

---

## 6. Current recommended model

Recommended primary model:

- `chatgpt-playwright`

Secondary / experimental:

- `chatgpt-authenticated`

---

## 7. Known limitations

- The proxy currently targets pi through `openai-completions`, not `openai-responses`.
- The authenticated Python path remains secondary/experimental compared to Playwright.
- Runtime continuity currently uses proxy-local in-memory conversation mapping.
- For real coding sessions, browser-backed transport reliability still depends on the local Chromium/CDP environment being healthy.
