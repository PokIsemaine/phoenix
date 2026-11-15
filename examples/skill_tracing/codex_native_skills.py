"""Bridge native Codex skill invocation logs to metadata-only OpenInference traces."""

from __future__ import annotations

import argparse
import hashlib
import json
import zlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from google.protobuf.json_format import MessageToJson, Parse, ParseError
from google.protobuf.message import DecodeError
from openinference.semconv.resource import ResourceAttributes
from openinference.semconv.trace import SpanAttributes
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceRequest,
    ExportLogsServiceResponse,
)
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.logs.v1.logs_pb2 import LogRecord
from opentelemetry.proto.trace.v1.trace_pb2 import Span

MAX_BODY_BYTES = 8 * 1024 * 1024
SKILL_EVENT = "codex.skill_invocation"


def convert_skill_log(record: LogRecord) -> Span | None:
    """Convert one detected invocation, without claiming loading or task success."""
    attributes = {
        attribute.key: attribute.value.string_value
        for attribute in record.attributes
        if attribute.value.WhichOneof("value") == "string_value"
    }
    if attributes.get("event.name", record.event_name) != SKILL_EVENT:
        return None
    required = ("conversation.id", "turn.id", "skill.name", "skill.invocation_type")
    if not all(attributes.get(key) for key in required):
        raise ValueError("Missing invocation identity")
    if attributes["skill.invocation_type"] not in {"explicit", "implicit"}:
        raise ValueError("Unknown invocation type")
    timestamp = record.time_unix_nano
    if not timestamp:
        event_time = datetime.fromisoformat(attributes.get("event.timestamp", ""))
        if event_time.tzinfo is None:
            raise ValueError("Event timestamp must include a timezone")
        delta = event_time.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
        timestamp = (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000
    if timestamp <= 0 or timestamp > 2**64 - 1:
        raise ValueError("Invalid event timestamp")
    identity = json.dumps([*[attributes[key] for key in required], timestamp]).encode()
    digest = hashlib.sha256(identity).digest()
    mapped = {
        SpanAttributes.OPENINFERENCE_SPAN_KIND: "TOOL",
        SpanAttributes.TOOL_NAME: SKILL_EVENT,
        SpanAttributes.SESSION_ID: attributes["conversation.id"],
        "phoenix.skill.name": attributes["skill.name"],
        "phoenix.skill.source": "codex_native",
        "phoenix.skill.observation": "invocation",
        "phoenix.skill.invocation_type": attributes["skill.invocation_type"],
        "codex.turn.id": attributes["turn.id"],
    }
    for source, target in (
        ("skill.scope", "codex.skill.scope"),
        ("skill.plugin_id", "codex.skill.plugin_id"),
        ("app.version", "codex.app.version"),
        ("originator", "codex.client.originator"),
    ):
        if attributes.get(source):
            mapped[target] = attributes[source]
    # No parent or duration is available in this event; one observation is one trace.
    return Span(
        trace_id=digest[:16],
        span_id=digest[16:24],
        name=f"skill invocation: {attributes['skill.name']}",
        kind=Span.SPAN_KIND_INTERNAL,
        start_time_unix_nano=timestamp,
        end_time_unix_nano=timestamp,
        attributes=[
            KeyValue(key=key, value=AnyValue(string_value=value)) for key, value in mapped.items()
        ],
    )


def create_app(
    *, endpoint: str, project: str, transport: httpx.AsyncBaseTransport | None = None
) -> FastAPI:
    """Create a loopback OTLP receiver that forwards only skill invocation metadata."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with httpx.AsyncClient(timeout=10, transport=transport, trust_env=False) as client:
            app.state.client = client
            yield

    app = FastAPI(lifespan=lifespan)

    @app.post("/v1/logs")
    async def receive_logs(request: Request) -> Response:
        content_type = request.headers.get("content-type", "").split(";")[0].strip()
        if content_type not in {"application/json", "application/x-protobuf"}:
            raise HTTPException(415, "Use OTLP JSON or protobuf")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BODY_BYTES:
                raise HTTPException(413, "OTLP batch too large")
        encoding = request.headers.get("content-encoding", "identity")
        if encoding not in {"identity", "gzip"}:
            raise HTTPException(415, "Unsupported content encoding")
        if encoding == "gzip":
            try:
                decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
                body = bytearray(decompressor.decompress(body, MAX_BODY_BYTES + 1))
            except zlib.error:
                raise HTTPException(400, "Invalid compressed OTLP batch") from None
            if len(body) > MAX_BODY_BYTES or decompressor.unconsumed_tail:
                raise HTTPException(413, "OTLP batch too large")
            if not decompressor.eof or decompressor.unused_data:
                raise HTTPException(400, "Invalid compressed OTLP batch")
        logs = ExportLogsServiceRequest()
        try:
            if content_type == "application/json":
                Parse(bytes(body), logs, ignore_unknown_fields=True)
            else:
                logs.ParseFromString(bytes(body))
        except (ParseError, DecodeError, UnicodeDecodeError):
            raise HTTPException(400, "Invalid OTLP batch") from None
        traces = ExportTraceServiceRequest()
        resource = traces.resource_spans.add()
        resource.resource.attributes.extend(
            [
                KeyValue(key=ResourceAttributes.PROJECT_NAME, value=AnyValue(string_value=project)),
                KeyValue(
                    key="service.name", value=AnyValue(string_value="phoenix-codex-native-skills")
                ),
            ]
        )
        scope = resource.scope_spans.add()
        scope.scope.name = "phoenix.examples.codex_native_skills"
        num_rejected = 0
        for resource_logs in logs.resource_logs:
            for scope_logs in resource_logs.scope_logs:
                for record in scope_logs.log_records:
                    try:
                        span = convert_skill_log(record)
                    except (ValueError, OverflowError):
                        num_rejected += 1
                        continue
                    if span is not None:
                        scope.spans.append(span)
        if scope.spans:
            try:
                response = await app.state.client.post(
                    endpoint,
                    content=traces.SerializeToString(),
                    headers={"content-type": "application/x-protobuf"},
                )
                response.raise_for_status()
                acknowledgement = ExportTraceServiceResponse.FromString(response.content)
            except (httpx.HTTPError, DecodeError):
                raise HTTPException(503, "Trace collector unavailable") from None
            if acknowledgement.partial_success.rejected_spans:
                raise HTTPException(503, "Trace collector rejected observations")
        result = ExportLogsServiceResponse()
        if num_rejected:
            result.partial_success.rejected_log_records = num_rejected
            result.partial_success.error_message = "Invalid skill invocation metadata"
        return Response(
            content=MessageToJson(result)
            if content_type == "application/json"
            else result.SerializeToString(),
            media_type=content_type,
        )

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:6006/v1/traces")
    parser.add_argument("--project", default="codex-native-skills")
    parser.add_argument("--port", type=int, default=6016)
    args = parser.parse_args()
    uvicorn.run(
        create_app(endpoint=args.endpoint, project=args.project), host="127.0.0.1", port=args.port
    )


if __name__ == "__main__":
    main()
