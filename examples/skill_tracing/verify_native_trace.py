"""Verify native skill observations persisted in Phoenix for a real Codex session."""

import argparse
import json
from pathlib import Path
from typing import Any

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:6006")
    parser.add_argument("--project", default="codex-native-skills")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--skill-name", required=True)
    parser.add_argument("--originator", required=True)
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
    assert spans, "No native skill observations persisted for this session"
    allowed = {
        "session.id",
        "tool.name",
        "phoenix.skill.name",
        "phoenix.skill.source",
        "phoenix.skill.observation",
        "phoenix.skill.invocation_type",
        "codex.turn.id",
        "codex.skill.scope",
        "codex.skill.plugin_id",
        "codex.app.version",
        "codex.client.originator",
    }
    for span in spans:
        attributes = span["attributes"]
        assert attributes["phoenix.skill.name"] == args.skill_name
        assert attributes["phoenix.skill.source"] == "codex_native"
        assert attributes["phoenix.skill.observation"] == "invocation"
        assert attributes["phoenix.skill.invocation_type"] in {"explicit", "implicit"}
        assert attributes["codex.client.originator"] == args.originator
        assert attributes["codex.turn.id"]
        assert set(attributes) <= allowed
        assert span["span_kind"] == "TOOL"
        assert span["status_code"] == "UNSET"
        assert span["start_time"] == span["end_time"]
        assert span["parent_id"] is None
        assert not span["events"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(spans, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"verified": True, "observations": len(spans), "session_id": args.session_id}))


if __name__ == "__main__":
    main()
