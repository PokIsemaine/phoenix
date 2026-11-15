# Validation record

Local Windows runs on 2026-11-15. MCP and native skill paths are verified
separately. This record does not claim completion of the entire issue's roadmap.

| Check | Result |
| --- | --- |
| Real Codex CLI, version 0.160.0 | Passed over HTTP MCP |
| Phoenix persisted REST readback | Three spans, all OK; parents and load backlinks verified |
| Python regression tests | 27 passed, 2 skipped, 214 deselected |
| Failed-load regression mutation | Both raised-error and returned-error tests fail when state is recorded before execution |
| Ruff and mypy for changed source/example code | Passed |
| Actual Codex Desktop chat, MCP | Passed; two actual MCP calls and three persisted OK spans |
| Native local skill, CLI 0.167.0-alpha.4.1 | Passed; successful local read, marker response, and persisted invocation |
| Native local skill, Desktop | Local read and marker passed; OTel delivery pending exporter activation |
| Native bridge and MCP example regressions | 8 passed |
| Codex CLI stdio MCP handshake | Did not pass locally; use HTTP for this example |

The targeted pytest selection was:

```text
tests/unit/server/agents/test_skill_tracing.py
tests/unit/server/agents/test_skill_requests.py
tests/unit/server/agents/pydantic_ai/test_openinference_capability_wrapper.py
tests/unit/server/agents/test_skill_tracing_mcp_example.py
tests/unit/server/agents/test_agents_router.py
-k "skill or wrap_tool" -q -o addopts=''
```

The router checks used SQLite. Skipped PostgreSQL cases are not a PostgreSQL pass.

## Recorded CLI example

- Project: `codex-skill-tracing`
- Session: `codex-cli-verified`
- Trace ID: `8a177e3eb9d51d0148cd26d95aab679b`
- Root span ID: `f98fc116afec1ccb`
- `load_skill` span ID: `fb2f7ee589827e60`
- `load_skill_reference` span ID: `91263ed5e7c638b3`
- Skill: `phoenix-tracing`
- Reference: `references/setup-python.md`

The CLI completed both MCP calls successfully. The server was gracefully stopped
to export its process-lifetime root, then `verify_trace.py` read back the trace
from Phoenix at `http://127.0.0.1:6010`. Re-running the example produces new IDs.

No credential values, skill bodies, prompts, or model outputs are included in
this record. The example's child spans exclude input/output contents and exception
messages. This does not assert a global privacy guarantee for other Phoenix spans.

## Recorded Desktop MCP example

- Desktop chat: `01a1df8a-dbbc-7a60-9216-07ffd6c8f173`
- Session: `codex-desktop-verified`
- Trace ID: `56eb7caca25d3149d78eea14ee28f5f7`
- The chat made actual `phoenix-skill-example-desktop.load_skill` and
  `load_skill_reference` calls; both completed. The REST verifier passed after
  graceful server shutdown. The test chat was archived after recording evidence.

## Recorded native CLI example

- Runtime: Codex CLI `0.167.0-alpha.4.1` (Desktop-bundled executable, run as CLI)
- Conversation: `01a1df9c-e058-7d41-b6ff-e94b7b500cc8`
- Skill: `phoenix-native-trace-demo`, a custom repository SKILL.md
- Actual file read: PowerShell `Get-Content`, exit code 0
- Actual final response: `PHOENIX_NATIVE_SKILL_OK`
- Phoenix observation trace: `45b2328a2fc5678565348642462218e7`
- Invocation type: `implicit`; status UNSET, with zero duration as documented
- `verify_native_trace.py` passed against the persisted Phoenix REST data.

## Remaining Desktop native check

Desktop chat `01a1df94-f043-7b71-a524-147220cf1dc3` successfully read the same
custom skill and replied with the marker. The running Desktop did not send a
native skill event after the log exporter was added, including in a fresh chat.
This is **not** an end-to-end pass. Activate the configured exporter, then repeat
the Desktop read and verify its conversation ID in Phoenix before closing this gap.
