import gzip
import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from google.protobuf.json_format import ParseDict
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)

from examples.skill_tracing import codex_native_skills


def _log(
    *, invocation: str = "implicit", timestamp: str = "2026-11-15T14:30:00.123456Z"
) -> dict[str, Any]:
    values = {
        "event.name": "codex.skill_invocation",
        "event.timestamp": timestamp,
        "conversation.id": "conversation-test",
        "turn.id": "turn-test",
        "skill.name": "any-custom-skill",
        "skill.invocation_type": invocation,
        "skill.scope": "repo",
        "originator": "codex_exec",
        "user.id": "PRIVATE_USER",
        "prompt": "PRIVATE_PROMPT",
    }
    return {
        "timeUnixNano": "0",
        "body": {"stringValue": "PRIVATE_BODY"},
        "attributes": [
            {"key": key, "value": {"stringValue": value}} for key, value in values.items()
        ],
    }


def _batch(*records: dict[str, Any]) -> dict[str, Any]:
    return {"resourceLogs": [{"scopeLogs": [{"logRecords": list(records)}]}]}


@pytest.mark.parametrize("binary", [False, True])
@pytest.mark.parametrize("compressed", [False, True])
def test_native_otlp_bridge_filters_content_and_preserves_invocation_identity(
    binary: bool,
    compressed: bool,
) -> None:
    exported: list[ExportTraceServiceRequest] = []

    def collect(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://collector/v1/traces"
        assert b"PRIVATE" not in request.content
        traces = ExportTraceServiceRequest.FromString(request.content)
        exported.append(traces)
        return httpx.Response(200)

    app = codex_native_skills.create_app(
        endpoint="http://collector/v1/traces",
        project="native-test",
        transport=httpx.MockTransport(collect),
    )
    batch = _batch(
        _log(invocation="explicit"), _log(), {"body": {"stringValue": "PRIVATE_OTHER_LOG"}}
    )
    body = (
        ParseDict(batch, ExportLogsServiceRequest()).SerializeToString()
        if binary
        else json.dumps(batch).encode()
    )
    headers = {"content-type": "application/x-protobuf" if binary else "application/json"}
    if compressed:
        body = gzip.compress(body)
        headers["content-encoding"] = "gzip"
    with TestClient(app) as client:
        for _ in range(2):
            response = client.post("/v1/logs", content=body, headers=headers)
            assert response.status_code == 200
    assert len(exported) == 2
    assert exported[0] == exported[1], "Retries must preserve span IDs for collector deduplication"
    spans = exported[0].resource_spans[0].scope_spans[0].spans
    assert len(spans) == 2
    assert spans[0].trace_id != spans[1].trace_id
    assert spans[0].span_id != spans[1].span_id
    for span in spans:
        assert span.start_time_unix_nano == span.end_time_unix_nano == 1794753000123456000
        assert span.status.code == 0
        assert not span.parent_span_id
        attributes = {attribute.key: attribute.value.string_value for attribute in span.attributes}
        assert attributes.pop("openinference.span.kind") == "TOOL"
        assert attributes.pop("tool.name") == "codex.skill_invocation"
        assert attributes.pop("session.id") == "conversation-test"
        assert attributes.pop("phoenix.skill.name") == "any-custom-skill"
        assert attributes.pop("phoenix.skill.source") == "codex_native"
        assert attributes.pop("phoenix.skill.observation") == "invocation"
        assert attributes.pop("phoenix.skill.invocation_type") in {"explicit", "implicit"}
        assert attributes.pop("codex.turn.id") == "turn-test"
        assert attributes.pop("codex.skill.scope") == "repo"
        assert attributes.pop("codex.client.originator") == "codex_exec"
        assert not attributes


def test_native_otlp_bridge_rejects_invalid_events_and_retries_collector_failures() -> None:
    attempts: list[bytes] = []

    def unavailable(request: httpx.Request) -> httpx.Response:
        attempts.append(request.content)
        return httpx.Response(503)

    app = codex_native_skills.create_app(
        endpoint="http://collector/v1/traces",
        project="test",
        transport=httpx.MockTransport(unavailable),
    )
    with TestClient(app) as client:
        invalid = client.post("/v1/logs", json=_batch(_log(timestamp="invalid")))
        assert invalid.status_code == 200
        assert invalid.json()["partialSuccess"]["rejectedLogRecords"] == "1"
        assert not attempts
        failure = client.post("/v1/logs", json=_batch(_log()))
        assert failure.status_code == 503
        assert len(attempts) == 1
        malformed = client.post(
            "/v1/logs", content=b"{", headers={"content-type": "application/json"}
        )
        assert malformed.status_code == 400
        unsupported = client.post("/v1/logs", content=b"anything")
        assert unsupported.status_code == 415


def test_native_otlp_bridge_bounds_compressed_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(codex_native_skills, "MAX_BODY_BYTES", 100)
    app = codex_native_skills.create_app(endpoint="http://collector/v1/traces", project="test")
    with TestClient(app) as client:
        response = client.post(
            "/v1/logs",
            content=gzip.compress(b" " * 1000),
            headers={"content-type": "application/json", "content-encoding": "gzip"},
        )
        assert response.status_code == 413


def test_native_otlp_bridge_does_not_acknowledge_rejected_trace_observations() -> None:
    def reject(request: httpx.Request) -> httpx.Response:
        result = ExportTraceServiceResponse()
        result.partial_success.rejected_spans = 1
        return httpx.Response(200, content=result.SerializeToString())

    app = codex_native_skills.create_app(
        endpoint="http://collector/v1/traces", project="test", transport=httpx.MockTransport(reject)
    )
    with TestClient(app) as client:
        response = client.post("/v1/logs", json=_batch(_log()))
        assert response.status_code == 503
