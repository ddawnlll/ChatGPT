import json

from tools.auth_flow_discovery import analysis_as_json, analysis_as_markdown, discover_stages, load_har


def _write_har(path):
    entries = [
        {
            "request": {
                "method": "GET",
                "url": "https://chatgpt.com/api/auth/session",
                "headers": [{"name": "Cookie", "value": "secret=1"}],
            },
            "response": {"status": 200},
        },
        {
            "request": {
                "method": "POST",
                "url": "https://chatgpt.com/backend-api/conversation",
                "headers": [
                    {"name": "Authorization", "value": "Bearer secret"},
                    {"name": "OAI-Client-Version", "value": "prod-test"},
                    {"name": "Content-Type", "value": "application/json"},
                ],
                "postData": {
                    "mimeType": "application/json",
                    "text": json.dumps(
                        {
                            "action": "next",
                            "messages": [{"id": "msg-1", "content": {"parts": ["hello"]}}],
                            "model": "auto",
                            "stream": True,
                            "history_and_training_disabled": False,
                            "authorization": "should-not-leak",
                        }
                    ),
                },
            },
            "response": {"status": 200},
        },
        {
            "request": {
                "method": "POST",
                "url": "https://chatgpt.com/backend-api/files",
                "headers": [{"name": "Authorization", "value": "Bearer secret"}],
                "postData": {"mimeType": "application/json", "text": json.dumps({"file_name": "a.png"})},
            },
            "response": {"status": 200},
        },
        {
            "request": {
                "method": "PATCH",
                "url": "https://chatgpt.com/backend-api/conversation/conv-1",
                "headers": [{"name": "Authorization", "value": "Bearer secret"}],
                "postData": {"mimeType": "application/json", "text": json.dumps({"title": "Hello"})},
            },
            "response": {"status": 200},
        },
        {
            "request": {
                "method": "GET",
                "url": "https://chatgpt.com/backend-api/conversations?offset=0&limit=28",
                "headers": [{"name": "Authorization", "value": "Bearer secret"}],
            },
            "response": {"status": 200},
        },
        {
            "request": {
                "method": "POST",
                "url": "https://example.com/not-chatgpt",
                "headers": [],
            },
            "response": {"status": 200},
        },
    ]
    path.write_text(json.dumps({"log": {"entries": entries}}))


def test_har_discovery_identifies_authenticated_stage_candidates(tmp_path):
    har_path = tmp_path / "capture.har"
    _write_har(har_path)

    stages = discover_stages(load_har(har_path))
    data = analysis_as_json(stages)

    assert data["summary"]["stage_count"] == 5
    assert data["summary"]["uses_backend_anon"] is False
    assert data["summary"]["authenticated_endpoint_families"] == ["api-auth", "backend-api"]
    assert data["summary"]["conversation_endpoint_candidates"] == ["https://chatgpt.com/backend-api/conversation"]
    assert "https://chatgpt.com/backend-api/files" in data["summary"]["file_endpoint_candidates"]
    assert "https://chatgpt.com/backend-api/conversations?offset=0&limit=28" in data["summary"]["history_or_title_endpoint_candidates"]

    conversation = next(stage for stage in data["stages"] if stage["stage"] == "conversation_send_or_stream")
    assert conversation["endpoint_family"] == "backend-api"
    assert conversation["important_headers"] == ["authorization", "content-type", "oai-client-version"]
    assert conversation["payload_findings"] == {
        "history_and_training_disabled": False,
        "messages_count": 1,
        "model_present": True,
        "stream": True,
    }


def test_markdown_report_omits_sensitive_values(tmp_path):
    har_path = tmp_path / "capture.har"
    _write_har(har_path)

    markdown = analysis_as_markdown(discover_stages(load_har(har_path)))

    assert "Bearer secret" not in markdown
    assert "should-not-leak" not in markdown
    assert "secret=1" not in markdown
    assert "backend-api/conversation" in markdown
    assert "history_and_training_disabled" in markdown
