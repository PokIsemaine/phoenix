"""Serve local skills over MCP and export metadata-only traces to Phoenix."""

from __future__ import annotations

import argparse
from pathlib import Path
from uuid import uuid4

import mcp_types
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult
from openinference.instrumentation import OITracer
from openinference.semconv.trace import SpanAttributes, ToolCallAttributes
from opentelemetry.context import Context
from opentelemetry.trace import NonRecordingSpan, StatusCode, format_span_id, set_span_in_context
from phoenix.otel import register

from phoenix.server.agents.skill_tracing import (
    SKILLS_AVAILABLE_ATTRIBUTE,
    SkillTraceState,
    get_available_skills_attribute,
    get_skill_tool_trace_metadata,
)
from phoenix.server.mcp.skills import (
    MCP_SKILLS_ROOT,
    Skill,
    get_skill_instructions,
    load_skills,
    register_skill_tools,
)


class SkillTracingMiddleware(Middleware):
    """Trace skill tools for one client session per server process."""

    def __init__(
        self, *, tracer: OITracer, skills: tuple[Skill, ...], parent: Context, session_id: str
    ) -> None:
        self.tracer = tracer
        self.skills_by_name = {skill.name: skill for skill in skills}
        self.parent = parent
        self.session_id = session_id
        self.state = SkillTraceState()
        self.client_session_id: str | None = None

    async def on_call_tool(
        self,
        context: MiddlewareContext[mcp_types.CallToolRequestParams],
        call_next: CallNext[mcp_types.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        if context.fastmcp_context is not None:
            client_session_id = context.fastmcp_context.session_id
            if self.client_session_id is None:
                self.client_session_id = client_session_id
            elif self.client_session_id != client_session_id:
                raise ToolError("This example accepts one client session per server process.")
        metadata = get_skill_tool_trace_metadata(
            tool_name=context.message.name,
            tool_args=context.message.arguments or {},
            skills_by_name=self.skills_by_name,
            state=self.state,
        )
        if metadata is None:
            return await call_next(context)
        parent = self.parent
        if metadata.parent_span_context is not None:
            parent = set_span_in_context(NonRecordingSpan(metadata.parent_span_context))
        request_id = context.fastmcp_context.request_id if context.fastmcp_context else str(uuid4())
        attributes = {
            **metadata.attributes,
            SpanAttributes.OPENINFERENCE_SPAN_KIND: "TOOL",
            SpanAttributes.TOOL_NAME: context.message.name,
            SpanAttributes.SESSION_ID: self.session_id,
            ToolCallAttributes.TOOL_CALL_ID: request_id,
            "phoenix.skill.call_id_source": "mcp_request_id",
        }
        with self.tracer.start_as_current_span(
            context.message.name,
            context=parent,
            attributes=attributes,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                result = await call_next(context)
            except BaseException:
                span.set_status(StatusCode.ERROR)
                raise
            span.set_status(StatusCode.ERROR if result.is_error else StatusCode.OK)
            if not result.is_error and metadata.is_load and metadata.skill_name is not None:
                self.state.loaded_span_ids[metadata.skill_name] = format_span_id(
                    span.get_span_context().span_id
                )
                self.state.loaded_span_contexts[metadata.skill_name] = span.get_span_context()
                self.state.loaded_tool_call_ids[metadata.skill_name] = request_id
            return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:6006/v1/traces")
    parser.add_argument("--project", default="codex-skill-tracing")
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--skill-root", type=Path, action="append")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--port", type=int, default=6012)
    args = parser.parse_args()
    skills = load_skills(tuple(args.skill_root or [MCP_SKILLS_ROOT]))
    session_id = args.session_id or str(uuid4())
    provider = register(
        endpoint=args.endpoint,
        project_name=args.project,
        protocol="http/protobuf",
        batch=False,
        verbose=False,
        set_global_tracer_provider=False,
    )
    tracer = provider.get_tracer("phoenix.examples.codex_skills")
    try:
        with tracer.start_as_current_span(
            "codex.mcp.skills",
            attributes={
                SpanAttributes.OPENINFERENCE_SPAN_KIND: "AGENT",
                SpanAttributes.SESSION_ID: session_id,
                SKILLS_AVAILABLE_ATTRIBUTE: get_available_skills_attribute(skills),
            },
        ) as root:
            server = FastMCP("Phoenix traced skills", instructions=get_skill_instructions(skills))
            register_skill_tools(server, skills)
            server.add_middleware(
                SkillTracingMiddleware(
                    tracer=tracer,
                    skills=skills,
                    parent=set_span_in_context(root),
                    session_id=session_id,
                )
            )
            try:
                if args.transport == "http":
                    server.run(
                        transport="http", host="127.0.0.1", port=args.port, show_banner=False
                    )
                else:
                    server.run(transport="stdio", show_banner=False)
            except KeyboardInterrupt:
                pass
            root.set_status(StatusCode.OK)
    finally:
        provider.shutdown()


if __name__ == "__main__":
    main()
