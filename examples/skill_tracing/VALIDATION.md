# Validation record

Local Windows run on 2026-11-15. This is evidence for the example's MCP path,
not for native Codex filesystem skills or the entire issue's roadmap.

| Check | Result |
| --- | --- |
| Real Codex CLI, version 0.160.0 | Passed over HTTP MCP |
| Phoenix persisted REST readback | Three spans, all OK; parents and load backlinks verified |
| Python regression tests | 27 passed, 2 skipped, 214 deselected |
| Failed-load regression mutation | Both raised-error and returned-error tests fail when state is recorded before execution |
| Ruff and mypy for changed source/example code | Passed |
| Actual Codex Desktop chat | Pending; not replaced by CLI or Phoenix browser tests |
| Native Codex filesystem skill tracing | Not implemented by this example |
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
