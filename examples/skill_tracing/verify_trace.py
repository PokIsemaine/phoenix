"""Verify a completed skill example using Phoenix's persisted REST representation."""

import argparse
import json
from pathlib import Path
from typing import Any

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:6006")
    parser.add_argument("--project", default="codex-skill-tracing")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    spans: list[dict[str, Any]] = []
    cursor: str | None = None
    with httpx.Client(base_url=args.endpoint, timeout=10) as client:
        while True:
            params: dict[str, str | int] = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            response = client.get(f"/v1/projects/{args.project}/spans", params=params)
            response.raise_for_status()
            page = response.json()
            spans.extend(
                span
                for span in page["data"]
                if span["attributes"].get("session.id") == args.session_id
            )
            cursor = page.get("next_cursor")
            if not cursor:
                break
    assert len(spans) == 3, f"Expected three persisted spans, got {len(spans)}"
    by_name = {span["name"]: span for span in spans}
    root = by_name["codex.mcp.skills"]
    load = by_name["load_skill"]
    reference = by_name["load_skill_reference"]
    assert len({span["context"]["trace_id"] for span in spans}) == 1
    assert all(span["status_code"] == "OK" for span in spans)
    assert load["parent_id"] == root["context"]["span_id"]
    assert reference["parent_id"] == load["context"]["span_id"]
    assert reference["attributes"]["phoenix.skill.load_span_id"] == load["context"]["span_id"]
    assert (
        reference["attributes"]["phoenix.skill.load_tool_call_id"]
        == load["attributes"]["tool_call.id"]
    )
    catalog = json.loads(root["attributes"]["phoenix.skills.available"])
    assert load["attributes"]["phoenix.skill.name"] in {skill["name"] for skill in catalog}
    for span in spans:
        assert "output.value" not in span["attributes"]
        assert "input.value" not in span["attributes"]
        assert "phoenix.skill.applied" not in span["attributes"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(spans, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"verified": True, "trace_id": root["context"]["trace_id"], "spans": 3}))


if __name__ == "__main__":
    main()
