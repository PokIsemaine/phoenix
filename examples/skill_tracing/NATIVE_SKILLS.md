# Native Codex skills

`codex_native_skills.py` receives Codex's native `codex.skill_invocation` OTel log
events and exports OpenInference-compatible observations to Phoenix. Any skill
name is accepted: repository skills, user skills, and plugin skills use the same
conversion. No change to individual SKILL.md files or OpenInference is required.

This is separate from `codex_mcp_skills.py`, which traces skills loaded through
MCP tools. Use both adapters if both loading paths matter.

## Start the bridge

With Phoenix running on port 6010:

```powershell
.\.venv\Scripts\python.exe examples/skill_tracing/codex_native_skills.py --endpoint http://127.0.0.1:6010/v1/traces --port 6016
```

The bridge binds only to `127.0.0.1`. It accepts OTLP HTTP JSON and protobuf,
including gzip, with an 8 MiB compressed and decompressed payload limit. It does
not expose an authenticated public ingestion service.

Configure the Codex **log** exporter (not `trace_exporter`):

```toml
[otel.exporter.otlp-http]
endpoint = "http://127.0.0.1:6016/v1/logs"
protocol = "json"
```

Merge this into your existing Codex configuration, preserving its other settings.
If you already have a log exporter, route through an OTel collector instead of
silently replacing that destination. Do not enable prompt or response logging
for this integration. The bridge ignores every non-skill log and uses an explicit
metadata allowlist; it does not persist the incoming request bodies.

Codex Desktop may require a restart after changing the exporter. A new chat alone
did not activate it in the local running Desktop instance. Verify actual received
events before declaring the Desktop path enabled.

## Exercise a custom local skill

The `native-workspace/` fixture contains a normal repository skill. Run an
event-capable Codex CLI in that workspace:

```powershell
codex --no-daemon exec -C examples/skill_tracing/native-workspace --json 'Use $phoenix-native-trace-demo. Read its SKILL.md and follow it. No MCP calls.'
```

Use a sandbox/approval policy that permits the fixture file to be read. An
attempted invocation event alone is not proof of a successful file read. The
real test requires the read command to succeed and the final response to be
`PHOENIX_NATIVE_SKILL_OK`, in addition to collector readback.

For Desktop, open the fixture workspace and issue the same prompt in an actual
Desktop chat. Preserve the chat's tool execution and response as separate
evidence; setting a CLI's originator string to `Codex_Desktop` is not verification.

Take the conversation ID from the real CLI JSONL or Desktop chat, then verify:

```powershell
.\.venv\Scripts\python.exe examples/skill_tracing/verify_native_trace.py --endpoint http://127.0.0.1:6010 --session-id <conversation-id> --skill-name phoenix-native-trace-demo --originator codex_exec --output native-trace.json
```

For Desktop use its observed originator instead of `codex_exec`. The verifier
checks metadata, scope, status, absent content, and the event-only timing contract.
It does not independently prove a successful skill read; check the client record.

## What the trace means

- Each native event becomes one zero-duration TOOL span with status UNSET. There
  is no invented parent span, execution duration, model-success claim, or tool ID.
- `session.id` is the actual Codex conversation ID; `codex.turn.id` groups turns.
  Each observation has its own trace. The event timestamp is retained (ISO string
  timestamps are represented at microsecond precision).
- `phoenix.skill.invocation_type` preserves explicit versus implicit detection.
  An explicit injection and a later implicit read are distinct observations.
- Hash/version and the available skill catalog are not supplied by this native
  event. This adapter does not invent them or read arbitrary files to infer them.
- Stable trace/span IDs make retried copies identifiable by the collector. The
  bridge returns 503 on downstream failure or partial rejection so Codex can
  retry. It has no durable queue; end-to-end delivery remains best effort.
- Content, prompts, outputs, paths, account IDs, user IDs, and unrelated log fields
  are discarded. Optional scope/plugin identity, app version and originator are
  preserved. OpenInference and OTel libraries provide the trace format; the
  `phoenix.*` and `codex.*` fields are adapter metadata, not new standardized enums.
- Codex must emit `codex.skill_invocation`. Native CLI validation used
  `0.167.0-alpha.4.1`; support must be checked by observing an event, not inferred
  from a version comparison. Shell-based implicit detection is best effort.

Upstream contract: [Codex skill invocation logs](https://github.com/openai/codex/blob/main/codex-rs/otel/README.md#skill-invocation-logs).
Wire protocol: [OTLP specification](https://opentelemetry.io/docs/specs/otlp/).
