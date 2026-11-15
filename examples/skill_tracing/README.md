# Codex skill tracing example

This example serves Phoenix skills over MCP and exports OpenInference spans to a
Phoenix collector. It reuses this branch's skill loader and identity metadata;
run it from this checkout with its Python dependencies installed. It does not
require changes to OpenInference or the Codex binary.

The Phoenix assistant instrumentation in `src/phoenix/server/agents/` does not
instrument external Codex processes. This example provides that separate MCP
boundary explicitly. The regular Phoenix `/mcp` endpoint does not automatically
gain these spans from the assistant wrapper.

## Run on Windows

Start Phoenix using a separate database and ports if another instance is running:

```powershell
New-Item -ItemType Directory -Force .scratch | Out-Null
.\.venv\Scripts\phoenix.exe serve --port 6010 --grpc-port 4318 --no-ui --database-url sqlite:///.scratch/skill-demo.db
```

In another terminal, start a single-client example server:

```powershell
.\.venv\Scripts\python.exe examples/skill_tracing/codex_mcp_skills.py --transport http --port 6013 --endpoint http://127.0.0.1:6010/v1/traces --session-id codex-cli-example
```

Register it with Codex. For an isolated test, use a separate `CODEX_HOME` with
your existing provider/auth configuration; never put credential values in command
arguments. Do not overwrite an existing server registration.

```powershell
codex mcp add phoenix-skill-example --url http://127.0.0.1:6013/mcp
codex --no-daemon exec "Use phoenix-skill-example only: load_skill for phoenix-tracing, then load_skill_reference for phoenix-tracing with reference_name references/setup-python.md. Do not modify files."
```

In Codex Desktop, load the same MCP registration in a fresh chat and submit the
same prompt. Run a separate example server process/session ID for each client.
Desktop verification requires an actual Desktop chat's tool calls and collector
readback; a CLI process with a Desktop origin label is not equivalent.

After the two calls finish, press Ctrl+C in the example server's terminal to
close the session root and flush the exporter. Then verify persisted spans:

```powershell
.\.venv\Scripts\python.exe examples/skill_tracing/verify_trace.py --endpoint http://127.0.0.1:6010 --session-id codex-cli-example --output .scratch/cli-trace.json
```

The verifier checks all three statuses, common trace ID, parent IDs, the load-call
backlink, available catalog membership, and the absence of captured bodies.

```text
codex.mcp.skills  AGENT
  load_skill  TOOL
    load_skill_reference  TOOL
```

## Contract and limits

- The root represents the example MCP process lifetime, not a Codex turn or LLM
  span. Child spans export immediately; the root exports on graceful shutdown.
- `--skill-root PATH` serves skill directories from a selected local catalog.
  It may be repeated. Without it, the public Phoenix MCP skills are served.
- The example supports the MCP initialize/session handshake used by the tested
  Codex client. It rejects a second client session to prevent sharing load state.
  It is not a multi-user production MCP service or a stateless-protocol adapter.
- `--transport stdio` is also available (and tested with the MCP Python SDK).
  The Windows Codex CLI verification uses HTTP; stdio handshaking with that CLI
  has not passed in the local environment.
- Skill output remains available to the client, but is not exported. Hash and
  content-version identify the served `SKILL.md`, not the whole reference tree.
- `tool_call.id` here is the MCP request ID, explicitly labeled with
  `phoenix.skill.call_id_source=mcp_request_id`; it is not Codex's model call ID.
- Reading a reference is `association=resource_read`; a tool following one loaded
  skill in the Phoenix assistant is `association=loaded_context`. Neither proves
  the model applied the instructions, so neither emits `applied=true`.
- This adapter observes skills loaded through its MCP tools. Direct native Codex
  filesystem skill reads are not captured. Recent upstream Codex versions document
  a `codex.skill_invocation` OTel log event; converting that event is a separate
  integration, not implemented or claimed verified by this example.

## Validation evidence

The unit test `tests/unit/server/agents/test_skill_tracing_mcp_example.py` invokes
the real FastMCP skill tools, checks failed reference reads, session isolation,
metadata privacy, and span relationships. The wrapper regression test verifies
that raised and returned load errors do not mark a skill as loaded.

The real CLI test additionally uses a running Phoenix server and the REST
verifier above. Keep Desktop runtime validation separate from Phoenix browser
assistant/router tests, which exercise a different product surface.
