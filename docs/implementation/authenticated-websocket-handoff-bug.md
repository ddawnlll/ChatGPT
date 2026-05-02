# Authenticated ChatGPT Web Flow Bug — Missing WebSocket Handoff Consumption

**Date:** 2026-05-03
**Status:** Identified
**Priority:** High
**Scope:** Authenticated transport (`transport_mode="authenticated"`)

---

## Summary

The authenticated ChatGPT web flow is currently incomplete.

The wrapper successfully completes:

- authenticated session preflight
- authenticated conversation prepare
- authenticated sentinel requirements prepare/finalize
- authenticated `POST /backend-api/f/conversation`

However, the wrapper does **not** yet consume the **post-handoff WebSocket stream** that contains the actual assistant response text.

As a result:

- the authenticated request appears to hang or return no answer
- local verification cannot complete
- sidebar/history verification is blocked by missing final streamed content handling

---

## Main Bug

### Current behavior

The authenticated `POST /backend-api/f/conversation` request returns only a handoff event stream such as:

- `event: delta_encoding`
- `data: "v1"`
- `data: {"type":"resume_conversation_token", ...}`
- `data: {"type":"stream_handoff", ...}`
- `data: [DONE]`

This response does **not** contain the final assistant text directly.

Instead, it instructs the browser to continue the turn through:

- `resume_sse_endpoint`
- and/or
- `subscribe_ws_topic`

In the real browser capture, the actual assistant text is delivered over **WebSocket** after subscribing to the `conversation-turn-...` topic.

---

## Evidence

### Authenticated HTTP response

Observed in the HAR for:

- `POST /backend-api/f/conversation`

The response includes:

```json
{
  "type": "stream_handoff",
  "conversation_id": "...",
  "turn_exchange_id": "...",
  "options": [
    {
      "type": "resume_sse_endpoint",
      "topic_id": "conversation-turn-..."
    },
    {
      "type": "subscribe_ws_topic",
      "topic_id": "conversation-turn-..."
    }
  ]
}
```

### Authenticated WebSocket behavior

Observed browser socket:

```text
wss://ws.chatgpt.com/p13/ws/user/user-<user_id>__<account_id>?verify=<token>
```

Initial browser commands:

```json
[
  {"id":1,"command":{"type":"connect","presence":{"type":"presence","state":"background"}}},
  {"id":2,"command":{"type":"subscribe","topic_id":"conversations"}},
  {"id":3,"command":{"type":"subscribe","topic_id":"app_notifications"}}
]
```

After `stream_handoff`, browser subscribes to the turn topic:

```json
[
  {
    "id":5,
    "command":{
      "type":"subscribe",
      "topic_id":"conversation-turn-da359f33-669b-4f57-9e9e-4e7b67400b1f",
      "offset":"0"
    }
  }
]
```

Incoming frames then contain the real assistant stream under:

```json
payload.payload.encoded_item
```

Examples include:

- `event: delta`
- `data: {"o":"patch", ...}`
- assistant text append chunks
- `message_stream_complete`

---

## Why the Wrapper Fails Today

The wrapper currently assumes that the authenticated conversation POST will produce a directly usable streamed or buffered answer.

That assumption is incorrect for the observed browser flow.

What is missing:

- open the ChatGPT WebSocket connection
- subscribe to the `conversation-turn-...` topic after `stream_handoff`
- parse `encoded_item` from websocket frames
- feed `encoded_item` into the existing event-stream parsing logic
- stop on completion markers such as `message_stream_complete`

---

## Root Cause

The authenticated implementation is missing the **post-handoff transport stage**.

More specifically:

1. The wrapper correctly reaches `stream_handoff`
2. The browser then switches to a topic-based websocket stream
3. The wrapper currently stops before consuming that websocket topic

---

## Fix Plan

### Required implementation

Implement authenticated websocket handoff support inside `wrapper/chatgpt.py`.

### Steps

1. **Capture WebSocket connection details**
   - derive websocket URL inputs:
     - user id
     - account id
     - verify token

2. **Open websocket connection**
   - connect to:
     - `wss://ws.chatgpt.com/p13/ws/user/{user_id}__{account_id}?verify={token}`

3. **Send initial websocket commands**
   - `connect`
   - subscribe `conversations`
   - subscribe `app_notifications`

4. **Handle `stream_handoff`**
   - extract `topic_id`
   - subscribe to:
     - `conversation-turn-...`

5. **Consume websocket messages**
   - inspect incoming arrays of messages
   - find:
     - `type: "message"`
     - `payload.type: "conversation-turn-stream"`
     - `payload.payload.encoded_item`

6. **Reuse existing parser**
   - pass `encoded_item` into the wrapper’s event-stream parsing logic
   - extract:
     - assistant text chunks
     - message state
     - completion markers

7. **Terminate correctly**
   - stop on:
     - `message_stream_complete`
     - or equivalent final assistant completion state

8. **Persist diagnostics**
   - record:
     - websocket connected
     - handoff topic id
     - websocket subscribe success
     - message stream complete

---

## Suggested Code Targets

Primary file:

- `wrapper/chatgpt.py`

Likely additions:

- websocket connection helper
- websocket bootstrap helper
- turn-topic subscribe helper
- websocket frame parser
- `encoded_item` stream consumer
- authenticated stream/send methods updated to continue after `stream_handoff`

Secondary updates:

- `manual_authenticated.py`
  - extend debug tracing for websocket connection/subscription
- `api_server.py`
  - no major architecture change required, but diagnostics should surface websocket handoff status

---

## Expected Result After Fix

Once websocket handoff is implemented correctly, authenticated mode should be able to:

- receive the actual assistant response text
- stream authenticated replies live
- persist remote conversation state correctly
- unblock Workstream G verification
- determine whether sidebar/history/title parity is truly achieved

---

## Not Yet Proven

This bug explains why authenticated replies are not currently materializing in the wrapper.

It does **not yet prove** that sidebar/history parity is fully solved.

After websocket handoff is fixed, the next verification step remains:

- confirm whether authenticated chats appear in `chatgpt.com` sidebar/history
- if not, identify the remaining missing browser sync/title/history stage

---

## One-Line Problem Statement

**Authenticated ChatGPT requests currently stop at `stream_handoff`; the real assistant answer is delivered over a websocket `conversation-turn-*` topic that the wrapper does not yet subscribe to or consume.**
