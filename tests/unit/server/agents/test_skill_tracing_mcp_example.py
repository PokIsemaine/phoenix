from pathlib import Path

from fastmcp import Client, FastMCP
from openinference.instrumentation import OITracer, TraceConfig
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode, format_span_id, set_span_in_context

from examples.skill_tracing.codex_mcp_skills import SkillTracingMiddleware
from phoenix.server.mcp.skills import Skill, SkillReference, register_skill_tools


async def test_mcp_skill_example_exports_metadata_and_links_successful_reads(
    tmp_path: Path,
) -> None:
    reference_path = tmp_path / "reference.md"
    reference_path.write_text("PRIVATE_REFERENCE", encoding="utf-8")
    skill = Skill(
        name="demo",
        description="Demo",
        summary="Demo",
        text="PRIVATE_SKILL",
        path=tmp_path,
        references=(SkillReference(name="references/example.md", path=reference_path),),
    )
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = OITracer(provider.get_tracer("test"), config=TraceConfig())
    with tracer.start_as_current_span("session") as root:
        server = FastMCP("test")
        register_skill_tools(server, (skill,))
        middleware = SkillTracingMiddleware(
            tracer=tracer, skills=(skill,), parent=set_span_in_context(root), session_id="test"
        )
        server.add_middleware(middleware)
        async with Client(server, mode="legacy") as client:
            loaded = await client.call_tool("load_skill", {"skill_name": "demo"})
            assert not loaded.is_error
            assert loaded.content[0].text == "PRIVATE_SKILL"
            read = await client.call_tool(
                "load_skill_reference",
                {"skill_name": "demo", "reference_name": "references/example.md"},
            )
            assert not read.is_error
            assert read.content[0].text == "PRIVATE_REFERENCE"
            # The file can disappear after the catalog was built; the load must fail visibly.
            reference_path.unlink()
            failed = await client.call_tool(
                "load_skill_reference",
                {"skill_name": "demo", "reference_name": "references/example.md"},
                raise_on_error=False,
            )
            assert failed.is_error
        async with Client(server, mode="legacy") as second_client:
            rejected = await second_client.call_tool(
                "load_skill", {"skill_name": "demo"}, raise_on_error=False
            )
            assert rejected.is_error
            assert "one client session" in rejected.content[0].text
    load, reference, failed_reference, root_span = exporter.get_finished_spans()
    assert load.parent.span_id == root_span.context.span_id
    assert reference.parent.span_id == load.context.span_id
    assert reference.attributes["phoenix.skill.load_span_id"] == format_span_id(
        load.context.span_id
    )
    assert reference.status.status_code == StatusCode.OK
    assert failed_reference.status.status_code == StatusCode.ERROR
    assert not failed_reference.events
    for span in (load, reference, failed_reference):
        assert "PRIVATE" not in str(span.attributes)
        assert "output.value" not in span.attributes
        assert "phoenix.skill.applied" not in span.attributes
    provider.shutdown()
