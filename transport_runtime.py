from __future__ import annotations

from dataclasses import dataclass
from json import dumps, loads
from pathlib import Path
from subprocess import PIPE, Popen
from typing import Any, Iterator, Protocol

from wrapper import ChatGPT


@dataclass
class TransportResult:
    text: str
    remote_conversation_id: str | None
    remote_parent_message_id: str | None
    transport_details: dict[str, Any]
    verification_hints: dict[str, Any]


class ChatTransport(Protocol):
    data: dict[str, Any]
    response: str

    def send_message(self, message: str, image: str | None = None, *, new_conversation: bool = True) -> TransportResult: ...
    def stream_message(self, message: str, image: str | None = None, *, new_conversation: bool = True) -> Iterator[str]: ...
    def get_last_result(self) -> TransportResult: ...
    def get_session_status(self) -> dict[str, Any]: ...
    def get_debug_summary(self) -> dict[str, Any]: ...
    def get_transport_audit(self) -> dict[str, Any]: ...


class ChatGPTTransport:
    def __init__(self, client: ChatGPT):
        self.client = client
        self.data = getattr(client, "data", {})
        self.response = getattr(client, "response", "")
        self._last_result = self._build_result(self.response)

    def _build_result(self, text: str) -> TransportResult:
        debug_summary = self.client.get_debug_summary()
        diagnostics = dict(debug_summary.get("request_diagnostics", {}))
        verification_hints = {
            "remote_conversation_exists": bool(
                diagnostics.get("remote_conversation_id") or self.client.data.get("conversation_id")
            ),
            "effective_transport_mode": diagnostics.get("effective_transport_mode"),
            "endpoint_family": diagnostics.get("endpoint_family"),
        }
        result = TransportResult(
            text=text,
            remote_conversation_id=self.client.data.get("conversation_id"),
            remote_parent_message_id=self.client.data.get("parent_message_id"),
            transport_details=diagnostics,
            verification_hints=verification_hints,
        )
        self.response = text
        self._last_result = result
        return result

    def send_message(self, message: str, image: str | None = None, *, new_conversation: bool = True) -> TransportResult:
        if image or new_conversation:
            text = self.client.ask_question(message, image)
        else:
            self.client.hold_conversation(message, new=False)
            text = self.client.response
        return self._build_result(text)

    def stream_message(self, message: str, image: str | None = None, *, new_conversation: bool = True) -> Iterator[str]:
        parts: list[str] = []
        if image or new_conversation:
            iterator = self.client.stream_question(message, image)
        else:
            iterator = self.client.hold_conversation_stream(message)

        for chunk in iterator:
            parts.append(chunk)
            yield chunk

        self._build_result("".join(parts))

    def get_last_result(self) -> TransportResult:
        return self._last_result

    def get_session_status(self) -> dict[str, Any]:
        return self.client.get_session_status()

    def get_debug_summary(self) -> dict[str, Any]:
        return self.client.get_debug_summary()

    def get_transport_audit(self) -> dict[str, Any]:
        return self.client.get_transport_audit()


class PlaywrightTransport:
    def __init__(self, session_material: dict[str, Any]):
        self.session_material = dict(session_material)
        self.data: dict[str, Any] = {"conversation_id": None, "parent_message_id": None}
        self.response: str = ""
        self._last_result = TransportResult("", None, None, {"transport_mode": "playwright"}, {})
        self.request_diagnostics: dict[str, Any] = {
            "selected_transport_mode": "playwright",
            "effective_transport_mode": "playwright",
            "endpoint_family": "browser-playwright",
        }
        self.event_callback = None

    def _script_path(self) -> str:
        return str(Path(__file__).resolve().parent / "tools" / "playwright_chat_transport.mjs")

    def _request_payload(self, message: str, image: str | None = None, *, new_conversation: bool = True) -> dict[str, Any]:
        return {
            "message": message,
            "image": image,
            "new_conversation": new_conversation,
            "remote_conversation_id": self.data.get("conversation_id"),
            "url": self.session_material.get("browser_chat_url") or "https://chatgpt.com/",
            "capture_timeout_ms": self.session_material.get("browser_capture_timeout_ms", 120000),
            "transport": {
                "mode": "playwright",
                "browser": {
                    "user_data_dir": self.session_material.get("browser_user_data_dir") or self.session_material.get("user_data_dir"),
                    "profile_directory": self.session_material.get("browser_profile_directory") or self.session_material.get("profile_directory"),
                    "executable_path": self.session_material.get("browser_executable_path") or self.session_material.get("executable_path"),
                    "channel": self.session_material.get("browser_channel"),
                    "headless": bool(self.session_material.get("browser_headless", False)),
                    "connect_over_cdp": bool(self.session_material.get("browser_connect_over_cdp", False)),
                    "cdp_url": self.session_material.get("browser_cdp_url"),
                    "auto_start_debug_browser": bool(self.session_material.get("browser_auto_start_debug_browser", False)),
                    "debugging_port": self.session_material.get("browser_debugging_port"),
                },
            },
        }

    def _build_result(self, payload: dict[str, Any]) -> TransportResult:
        self.response = payload.get("text") or ""
        self.data["conversation_id"] = payload.get("remote_conversation_id")
        self.data["parent_message_id"] = payload.get("remote_parent_message_id")
        transport_details = dict(payload.get("transport_details") or {})
        verification_hints = dict(payload.get("verification_hints") or {})
        self.request_diagnostics = {
            **self.request_diagnostics,
            **transport_details,
            "remote_conversation_id": self.data.get("conversation_id"),
            "remote_parent_message_id": self.data.get("parent_message_id"),
        }
        self._last_result = TransportResult(
            text=self.response,
            remote_conversation_id=self.data.get("conversation_id"),
            remote_parent_message_id=self.data.get("parent_message_id"),
            transport_details=self.request_diagnostics,
            verification_hints=verification_hints,
        )
        return self._last_result

    def _run(self, message: str, image: str | None = None, *, new_conversation: bool = True) -> Iterator[dict[str, Any]]:
        process = Popen(
            ["node", self._script_path()],
            stdin=PIPE,
            stdout=PIPE,
            stderr=PIPE,
            text=True,
            bufsize=1,
        )
        payload = dumps(self._request_payload(message, image, new_conversation=new_conversation))
        assert process.stdin is not None
        process.stdin.write(payload)
        process.stdin.close()

        saw_output = False
        assert process.stdout is not None
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            saw_output = True
            event = loads(line)
            if callable(self.event_callback):
                try:
                    self.event_callback(event)
                except Exception:
                    pass
            yield event

        stderr = process.stderr.read().strip() if process.stderr is not None else ""
        return_code = process.wait()
        if return_code not in {0, None}:
            if stderr:
                self.request_diagnostics["playwright_stderr"] = stderr[:1000]
            if not saw_output:
                raise RuntimeError(f"Playwright transport failed before emitting events: {stderr or 'unknown error'}")

    def send_message(self, message: str, image: str | None = None, *, new_conversation: bool = True) -> TransportResult:
        final_payload: dict[str, Any] | None = None
        for event in self._run(message, image, new_conversation=new_conversation):
            if event.get("type") == "status":
                self.request_diagnostics.update({"last_stage": event.get("stage")})
            elif event.get("type") == "result":
                final_payload = event
        if not final_payload:
            raise RuntimeError("Playwright transport did not emit a final result event")
        if not final_payload.get("success"):
            raise RuntimeError(final_payload.get("error") or "Playwright transport request failed")
        return self._build_result(final_payload)

    def stream_message(self, message: str, image: str | None = None, *, new_conversation: bool = True) -> Iterator[str]:
        final_payload: dict[str, Any] | None = None
        for event in self._run(message, image, new_conversation=new_conversation):
            if event.get("type") == "status":
                self.request_diagnostics.update({"last_stage": event.get("stage")})
            elif event.get("type") == "chunk":
                chunk = event.get("content") or ""
                if chunk:
                    yield chunk
            elif event.get("type") == "result":
                final_payload = event
        if not final_payload:
            raise RuntimeError("Playwright transport did not emit a final result event")
        if not final_payload.get("success"):
            raise RuntimeError(final_payload.get("error") or "Playwright transport request failed")
        self._build_result(final_payload)

    def get_last_result(self) -> TransportResult:
        return self._last_result

    def get_session_status(self) -> dict[str, Any]:
        return {
            "transport_mode": "playwright",
            "browser_user_data_dir": self.session_material.get("browser_user_data_dir") or self.session_material.get("user_data_dir"),
            "browser_profile_directory": self.session_material.get("browser_profile_directory") or self.session_material.get("profile_directory"),
            "browser_executable_path_present": bool(self.session_material.get("browser_executable_path") or self.session_material.get("executable_path")),
            "browser_connect_over_cdp": bool(self.session_material.get("browser_connect_over_cdp", False)),
            "browser_cdp_url": self.session_material.get("browser_cdp_url"),
        }

    def get_debug_summary(self) -> dict[str, Any]:
        return {
            "request_diagnostics": dict(self.request_diagnostics),
            "last_request_summary": {"transport_mode": "playwright"},
            "last_response_summary": {"response_length": len(self.response)},
        }

    def get_transport_audit(self) -> dict[str, Any]:
        return {
            "selected_transport_mode": "playwright",
            "execution_engine": "playwright-browser",
            "browser_user_data_dir": self.session_material.get("browser_user_data_dir") or self.session_material.get("user_data_dir"),
            "browser_profile_directory": self.session_material.get("browser_profile_directory") or self.session_material.get("profile_directory"),
            "browser_connect_over_cdp": bool(self.session_material.get("browser_connect_over_cdp", False)),
            "browser_cdp_url": self.session_material.get("browser_cdp_url"),
        }


def build_chatgpt_transport(session_material: dict[str, Any]) -> ChatTransport:
    client = ChatGPT(
        proxy=session_material.get("proxy"),
        cookies=session_material.get("cookies"),
        authorization=session_material.get("authorization"),
        thinking_mode=session_material.get("thinking_mode", "instant"),
        model_name=session_material.get("model_name", "auto"),
        transport_mode=session_material.get("transport_mode", "authenticated"),
        allow_anon_fallback=session_material.get("allow_anon_fallback", False),
        endpoint_overrides=session_material.get("endpoint_overrides"),
        extra_headers=session_material.get("extra_headers"),
        websocket_url=session_material.get("websocket_url"),
        websocket_verify_token=session_material.get("websocket_verify_token"),
    )
    return ChatGPTTransport(client)


def build_transport(session_material: dict[str, Any]) -> ChatTransport:
    if (session_material.get("transport_mode") or "authenticated").strip().lower() == "playwright":
        return PlaywrightTransport(session_material)
    return build_chatgpt_transport(session_material)
