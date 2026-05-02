#!/usr/bin/env python3
"""Analyze user-exported ChatGPT browser traffic for authenticated web-flow discovery.

This tool intentionally does not log in, scrape browser secrets, or call ChatGPT.
It consumes user-observable browser DevTools exports, redacts sensitive material,
and emits a stage-oriented request inventory that can be used to implement the
private authenticated web flow from evidence instead of guesses.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

SENSITIVE_HEADER_NAMES = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-csrf-token",
    "openai-sentinel-chat-requirements-token",
    "openai-sentinel-proof-token",
    "openai-sentinel-turnstile-token",
    "x-conduit-token",
}
SENSITIVE_KEY_FRAGMENTS = (
    "token",
    "cookie",
    "authorization",
    "secret",
    "password",
    "csrf",
    "arkose",
    "turnstile",
    "proof",
)
IMPORTANT_HEADER_NAMES = {
    "accept",
    "authorization",
    "content-type",
    "cookie",
    "oai-client-version",
    "oai-device-id",
    "oai-language",
    "oai-time-zone",
    "openai-sentinel-chat-requirements-token",
    "openai-sentinel-proof-token",
    "openai-sentinel-turnstile-token",
    "referer",
    "user-agent",
    "x-conduit-token",
}


@dataclass
class TrafficRequest:
    index: int
    method: str
    url: str
    status: int | None = None
    headers: dict[str, str] = field(default_factory=dict)
    payload: Any = None


@dataclass
class DiscoveredStage:
    index: int
    stage: str
    method: str
    url: str
    endpoint_family: str
    status: int | None
    important_headers: list[str]
    payload_fields: list[str]
    payload_findings: dict[str, Any]


def _redacted(value: Any) -> str:
    if value in (None, ""):
        return ""
    return "<redacted>"


def _redact_mapping(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, nested in value.items():
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in SENSITIVE_KEY_FRAGMENTS):
                result[key] = _redacted(nested)
            else:
                result[key] = _redact_mapping(nested)
        return result
    if isinstance(value, list):
        return [_redact_mapping(item) for item in value]
    return value


def _headers_from_har(raw_headers: list[dict[str, Any]]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for header in raw_headers or []:
        name = str(header.get("name", "")).strip()
        if not name:
            continue
        headers[name.lower()] = str(header.get("value", ""))
    return headers


def _parse_payload(post_data: dict[str, Any] | None) -> Any:
    if not post_data:
        return None
    text = post_data.get("text")
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"_raw_body_type": post_data.get("mimeType") or "unknown", "_raw_body_present": True}


def load_har(path: Path) -> list[TrafficRequest]:
    data = json.loads(path.read_text())
    entries = data.get("log", {}).get("entries", [])
    requests: list[TrafficRequest] = []
    for index, entry in enumerate(entries, start=1):
        request = entry.get("request", {})
        response = entry.get("response", {})
        requests.append(
            TrafficRequest(
                index=index,
                method=str(request.get("method", "GET")).upper(),
                url=str(request.get("url", "")),
                status=response.get("status"),
                headers=_headers_from_har(request.get("headers", [])),
                payload=_parse_payload(request.get("postData")),
            )
        )
    return requests


def sanitize_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path
    path = re.sub(r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?=/|$)", "/<conversation_id>", path, flags=re.IGNORECASE)
    path = re.sub(r"/file_[A-Za-z0-9]+(?=/|$)", "/<file_id>", path)
    safe_query = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if any(fragment in lowered for fragment in SENSITIVE_KEY_FRAGMENTS) or key in {"post_id"}:
            safe_query.append((key, "<redacted>" if value else ""))
        else:
            safe_query.append((key, value))
    return urlunparse((parsed.scheme, parsed.netloc, path, "", urlencode(safe_query), ""))


def endpoint_family(url: str) -> str:
    path = urlparse(url).path
    if "/backend-anon/" in path:
        return "backend-anon"
    if "/backend-api/" in path:
        return "backend-api"
    if "/public-api/" in path:
        return "public-api"
    if "/api/auth/" in path:
        return "api-auth"
    if "/cdn-cgi/" in path:
        return "cloudflare"
    return "other"


def classify_stage(request: TrafficRequest) -> str | None:
    parsed = urlparse(request.url)
    if not parsed.netloc.endswith("chatgpt.com") and "chat.openai.com" not in parsed.netloc:
        return None

    path = parsed.path.lower()
    method = request.method
    payload_text = json.dumps(request.payload or {}, sort_keys=True).lower()

    if path.endswith("/f/conversation/prepare") and method == "POST":
        return "prepare_conversation"
    if path.endswith("/f/conversation") and method == "POST":
        return "conversation_send_or_stream"
    if path.endswith("/conversation") and method == "POST":
        return "conversation_send_or_stream"
    if "conversation" in path and "stream_status" in path:
        return "post_send_stream_status"
    if "conversation" in path and "textdocs" in path:
        return "post_send_artifact_sync"
    if "conversation" in path and "generate_autocompletions" in path:
        return "autocomplete"
    if "conversation" in path and method in {"PATCH", "PUT"}:
        return "conversation_metadata_update"
    if "conversation" in path and "title" in path:
        return "title_generation_or_update"
    if "conversations" in path or "history" in path:
        return "sidebar_or_history_sync"
    if "files" in path or "upload" in path or "attachment" in path:
        return "file_upload_or_attachment"
    if "models" in path:
        return "model_discovery"
    if "session" in path or "accounts" in path:
        return "session_or_account_bootstrap"
    if "sentinel" in path or "arkose" in path or "turnstile" in path or "proof" in payload_text:
        return "challenge_or_requirements"
    return None


def payload_fields(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        return sorted(str(key) for key in payload.keys())
    if payload is None:
        return []
    return ["<non-json-body>"]


def payload_findings(payload: Any) -> dict[str, Any]:
    findings: dict[str, Any] = {}
    if not isinstance(payload, dict):
        return findings
    if "history_and_training_disabled" in payload:
        findings["history_and_training_disabled"] = payload["history_and_training_disabled"]
    if "conversation_id" in payload:
        findings["conversation_id_present"] = bool(payload.get("conversation_id"))
    if "parent_message_id" in payload:
        findings["parent_message_id_present"] = bool(payload.get("parent_message_id"))
    if "messages" in payload:
        findings["messages_count"] = len(payload.get("messages") or [])
    if "model" in payload:
        findings["model_present"] = bool(payload.get("model"))
    if "stream" in payload:
        findings["stream"] = payload.get("stream")
    return findings


def discover_stages(requests: list[TrafficRequest]) -> list[DiscoveredStage]:
    stages: list[DiscoveredStage] = []
    for request in requests:
        stage = classify_stage(request)
        if not stage:
            continue
        important_headers = sorted(
            header for header in request.headers.keys() if header in IMPORTANT_HEADER_NAMES
        )
        stages.append(
            DiscoveredStage(
                index=request.index,
                stage=stage,
                method=request.method,
                url=sanitize_url(request.url),
                endpoint_family=endpoint_family(request.url),
                status=request.status,
                important_headers=important_headers,
                payload_fields=payload_fields(request.payload),
                payload_findings=payload_findings(request.payload),
            )
        )
    return stages


def summarize(stages: list[DiscoveredStage]) -> dict[str, Any]:
    by_stage: dict[str, int] = {}
    endpoint_families: dict[str, int] = {}
    for stage in stages:
        by_stage[stage.stage] = by_stage.get(stage.stage, 0) + 1
        endpoint_families[stage.endpoint_family] = endpoint_families.get(stage.endpoint_family, 0) + 1

    conversation_stages = [stage for stage in stages if stage.stage == "conversation_send_or_stream"]
    file_stages = [stage for stage in stages if stage.stage == "file_upload_or_attachment"]
    history_stages = [stage for stage in stages if stage.stage in {"sidebar_or_history_sync", "title_generation_or_update", "conversation_metadata_update"}]

    return {
        "stage_count": len(stages),
        "stage_counts": by_stage,
        "endpoint_family_counts": endpoint_families,
        "authenticated_endpoint_families": sorted(
            family for family in endpoint_families if family not in {"backend-anon", "other"}
        ),
        "uses_backend_anon": endpoint_families.get("backend-anon", 0) > 0,
        "conversation_endpoint_candidates": sorted({stage.url for stage in conversation_stages}),
        "file_endpoint_candidates": sorted({stage.url for stage in file_stages}),
        "history_or_title_endpoint_candidates": sorted({stage.url for stage in history_stages}),
    }


def analysis_as_json(stages: list[DiscoveredStage]) -> dict[str, Any]:
    return {
        "summary": summarize(stages),
        "stages": [stage.__dict__ for stage in stages],
    }


def analysis_as_markdown(stages: list[DiscoveredStage]) -> str:
    data = analysis_as_json(stages)
    summary = data["summary"]
    lines = [
        "# Authenticated ChatGPT Browser Traffic Discovery",
        "",
        "Sensitive header/body values are redacted or omitted. This report is derived only from user-exported browser traffic.",
        "",
        "## Summary",
        f"- Matching stages: {summary['stage_count']}",
        f"- Endpoint families: `{json.dumps(summary['endpoint_family_counts'], sort_keys=True)}`",
        f"- Uses backend-anon: `{summary['uses_backend_anon']}`",
        f"- Authenticated endpoint families: `{', '.join(summary['authenticated_endpoint_families']) or 'none observed'}`",
        "",
        "## Stage Inventory",
        "",
        "| # | Stage | Method | Family | Status | URL | Headers | Payload fields | Findings |",
        "|---:|---|---|---|---:|---|---|---|---|",
    ]
    for stage in stages:
        lines.append(
            "| {index} | {stage} | {method} | {family} | {status} | `{url}` | `{headers}` | `{fields}` | `{findings}` |".format(
                index=stage.index,
                stage=stage.stage,
                method=stage.method,
                family=stage.endpoint_family,
                status=stage.status if stage.status is not None else "",
                url=stage.url,
                headers=", ".join(stage.important_headers),
                fields=", ".join(stage.payload_fields),
                findings=json.dumps(stage.payload_findings, sort_keys=True),
            )
        )
    lines.extend([
        "",
        "## Endpoint Candidates",
        "",
        "### Conversation send/stream",
        *[f"- `{url}`" for url in summary["conversation_endpoint_candidates"]],
        "",
        "### File upload/attachment",
        *[f"- `{url}`" for url in summary["file_endpoint_candidates"]],
        "",
        "### History/title/sidebar sync",
        *[f"- `{url}`" for url in summary["history_or_title_endpoint_candidates"]],
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze a ChatGPT DevTools HAR export for authenticated web-flow discovery.")
    parser.add_argument("har", type=Path, help="Path to a browser DevTools HAR export")
    parser.add_argument("--format", choices={"json", "markdown"}, default="markdown")
    parser.add_argument("--output", type=Path, help="Optional output path")
    args = parser.parse_args()

    stages = discover_stages(load_har(args.har))
    if args.format == "json":
        output = json.dumps(analysis_as_json(stages), indent=2, sort_keys=True)
    else:
        output = analysis_as_markdown(stages)

    if args.output:
        args.output.write_text(output + "\n")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
