# ai_summary

repo_kind: reverse_engineered_chatgpt_web_client
primary_function: emulate_chatgpt_web_sessions_and_send_messages_without_official_openai_api
runtime_language: python
secondary_artifact: decompiled_js_reference

## semantic_overview
- The codebase implements a local FastAPI wrapper around a custom ChatGPT web client.
- It emulates browser behavior, fetches cookies, derives IP/geolocation/timezone data, and reproduces private request headers.
- It contains reverse-engineering logic for ChatGPT anti-bot / challenge flows:
  - requirements token
  - proof-of-work token
  - turnstile token generated from decompiled VM bytecode
- It also supports multimodal image upload via ChatGPT file endpoints.

## top_level_entrypoints
- api_server.py: exposes POST /conversation on localhost:6969.
- manual.py: simple CLI test entrypoint calling ChatGPT().ask_question("Test").
- wrapper/chatgpt.py: main orchestration client.

## external_behavior
### input
- proxy: optional HTTP proxy string.
- message: user prompt text.
- image: optional base64 data URI image.

### output
- returns assistant response text parsed from ChatGPT SSE/event-stream style response.

## file_tree

```text
.
├── Makefile                           # High-level entrypoints for setup, shell, and starting servers
├── api_server.py                      # Original FastAPI backend exposing non-standard /conversation endpoints
├── transport_runtime.py               # Abstracted chat interfaces unifying authenticated, playwright, and proxy streams
├── manual*.py                         # Various CLI test entrypoints (simple, authenticated, hybrid)
├── requirements.txt                   # Auto-generated python dependencies
├── wrapper/                           # Core Reverse-Engineered Web Client
│   ├── chatgpt.py                     # Main ChatGPT HTTP wrapper maintaining session headers and parsing SSE
│   ├── paths.py                       # Cross-platform resolution of local Playwright browsers and isolated profiles
│   ├── reverse/                       # Logic imitating anti-bot JS challenges (Turnstile, PoW)
│   ├── IP_Info/                       # Fakes IP/Timezone telemetry matching the expected client metrics
│   └── logger.py / runtime.py         # Utils for console output and exception wrappers
├── tools/                             # Playwright JS/Python Automation Scripts
│   ├── setup_browser.py               # Pulls/forces Playwright Chromium binaries to bypass MacOS/Gatekeeper limits
│   ├── setup_pi_provider.py           # Merges the proxy endpoint into `~/.pi/agent/models.json`
│   ├── playwright_chat_transport.mjs  # A robust headless JS client injecting scripts to bypass Turnstile natively
│   ├── extract_authenticated_session.mjs # Drives Chrome to capture initial WS/Auth cookies
│   └── paths.mjs                      # JS companion to wrapper/paths.py for local browser resolution
├── proxy/                             # OpenAI-Compatible Backend Server
│   ├── app/                           # Full FastAPI structure translating /v1/chat/completions into local Web calls
│   └── ai_summary.md                  # Dedicated proxy architecture overview
├── docs/                              # Project Design and Summaries
│   ├── ai_summary.md                  # This semantic context summary
│   └── implementation/                # Detailed guides for proxy validation and authenticated session transport
├── frontend/                          # Local web UI built in React / Vite connecting to api_server.py
└── tests/                             # Pytest suite validating token patching, HTTP formats, and proxy parsing
```

## request_flow
1. instantiate curl_cffi session impersonating chrome.
2. load https://chatgpt.com to collect cookies and build client metadata.
3. fetch IP and timezone info from external lookup sites.
4. build config payload used to generate a VM token.
5. POST /backend-anon/sentinel/chat-requirements with p=vm_token.
6. receive:
   - token
   - proofofwork challenge
   - turnstile bytecode
7. POST /backend-anon/f/conversation/prepare to obtain conduit token.
8. solve proof-of-work.
9. decompile turnstile bytecode and synthesize turnstile token.
10. POST /backend-anon/f/conversation with required headers and conversation payload.
11. parse streamed response data and concatenate assistant content parts.

## notable_modules
### wrapper/chatgpt.py
- ChatGPT class is the core client.
- manages session headers, cookies, proxies, conversation state, file uploads, and response parsing.
- methods of interest:
  - _fetch_cookies()
  - _get_tokens()
  - get_conduit()
  - upload_file()
  - ask_question()
  - ask_question_with_file()
  - _parse_event_stream()

### wrapper/reverse/challenges.py
- generate_token(config): encodes config into gAAAAAC... style token.
- solve_pow(seed, difficulty, config): brute-force style solver returning gAAAAAB... style token.
- mod(): hashing/check function used for difficulty comparison.

### wrapper/reverse/decompiler.py
- translates custom VM bytecode into JS-like decompiled output.
- maps numeric opcodes to symbolic operations.
- emits synthetic JS for analysis by parser.

### wrapper/reverse/parse.py
- esprima-based parser over decompiled JS.
- extracts assignments and XOR key material.
- identifies usage patterns such as:
  - location
  - ipinfo
  - vendor
  - localstorage
  - element
  - history
  - random
  - singlebtoa / doublexor

### wrapper/reverse/vm.py
- builds final turnstile token payload.
- uses extracted key/value semantics from parser.
- injects synthetic browser-fingerprint values such as navigator, localStorage, location, element metrics, and random values.
- serializes payload, XORs with key, base64-encodes result.

### wrapper/IP_Info/ip_info.py
- scrapes IP, city, region, lat, lng, timezone from third-party sites.

### wrapper/IP_Info/headers.py
- contains canned header sets for different phases:
  - DEFAULT
  - REQUIREMENTS
  - CONDUIT
  - CONVERSATION
  - FILE

### wrapper/logger.py
- colored console logger.

### wrapper/runtime.py
- helper utilities and a decorator for exception handling.

## data_structures
### ChatGPT.data
- prod: client build version from chatgpt.com HTML data-build attribute
- device-id: oai-did cookie
- config: synthetic fingerprint config list
- vm_token: generated token for requirements request
- token: requirements response token
- proofofwork: challenge object
- bytecode: turnstile VM bytecode
- conversation_id: current conversation id
- parent_message_id: current parent message id

### conversation payload shape
- action: next
- messages: list with one user message object
- timezone_offset_min / timezone from IP lookup
- history_and_training_disabled: true
- conversation_mode.kind: primary_assistant
- supports_buffering: true
- supported_encodings: ["v1"]
- client_contextual_info: fixed browser-like dimensions and timing fields

## implementation_characteristics
- The repo is tightly coupled to private ChatGPT web endpoints and expected response shapes.
- It attempts to look like Chrome on Windows with German locale settings.
- It uses proxies to vary perceived source IP.
- It relies on brittle heuristics and string parsing.
- It is likely to break when OpenAI changes the frontend, bytecode format, headers, or response schema.

## files_likely_used_for_reverse_engineering
- decompiled.js: sample/generated decompiled VM output.
- images/: screenshots referenced in the README.

## caution
- This repository is an unofficial reverse-engineered client, not an official API integration.
- It may violate service terms depending on usage.
- When summarizing or extending the code, treat private endpoints and token logic as implementation details rather than public API guarantees.
