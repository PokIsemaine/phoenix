from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from opentelemetry.trace import SpanContext

from phoenix.server.mcp.skills import (
    LOAD_SKILL_REFERENCE_TOOL_NAME,
    LOAD_SKILL_TOOL_NAME,
    Skill,
)

SKILL_NAME_ATTRIBUTE = "phoenix.skill.name"
SKILL_SOURCE_ATTRIBUTE = "phoenix.skill.source"
SKILL_VERSION_ATTRIBUTE = "phoenix.skill.version"
SKILL_HASH_ATTRIBUTE = "phoenix.skill.hash"
SKILL_ORIGIN_ATTRIBUTE = "phoenix.skill.origin"
SKILL_RESOURCE_PATH_ATTRIBUTE = "phoenix.skill.resource_path"
SKILL_LOAD_SPAN_ID_ATTRIBUTE = "phoenix.skill.load_span_id"
SKILL_LOAD_TOOL_CALL_ID_ATTRIBUTE = "phoenix.skill.load_tool_call_id"
SKILL_ASSOCIATION_ATTRIBUTE = "phoenix.skill.association"
SKILLS_AVAILABLE_ATTRIBUTE = "phoenix.skills.available"


@dataclass
class SkillTraceState:
    """Per-agent state used to link skill resource reads to their load spans."""

    loaded_span_ids: dict[str, str] = field(default_factory=dict)
    loaded_span_contexts: dict[str, SpanContext] = field(default_factory=dict)
    loaded_tool_call_ids: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillToolTraceMetadata:
    attributes: Mapping[str, Any]
    capture_output: bool
    skill_name: str | None = None
    is_load: bool = False
    parent_span_context: SpanContext | None = None


def get_skill_metadata(skill: Skill) -> dict[str, str]:
    """Return privacy-safe identity metadata for a skill."""
    content_hash = hashlib.sha256(skill.text.encode("utf-8")).hexdigest()
    normalized_path = skill.path.as_posix()
    source = (
        "builtin"
        if "/server/agents/prompts/" in normalized_path or "/server/mcp/skills/" in normalized_path
        else "external"
    )
    return {
        SKILL_NAME_ATTRIBUTE: skill.name,
        SKILL_SOURCE_ATTRIBUTE: source,
        SKILL_VERSION_ATTRIBUTE: content_hash,
        SKILL_HASH_ATTRIBUTE: content_hash,
    }


def get_available_skills_attribute(skills: list[Skill] | tuple[Skill, ...]) -> str:
    """Serialize the turn's available skill catalog without skill contents."""
    import json

    catalog = [
        {
            "name": metadata[SKILL_NAME_ATTRIBUTE],
            "source": metadata[SKILL_SOURCE_ATTRIBUTE],
            "version": metadata[SKILL_VERSION_ATTRIBUTE],
            "hash": metadata[SKILL_HASH_ATTRIBUTE],
        }
        for skill in skills
        for metadata in (get_skill_metadata(skill),)
    ]
    return json.dumps(catalog, separators=(",", ":"), sort_keys=True)


def get_skill_tool_trace_metadata(
    *,
    tool_name: str,
    tool_args: Mapping[str, Any],
    skills_by_name: Mapping[str, Skill],
    state: SkillTraceState,
) -> SkillToolTraceMetadata | None:
    """Build trace metadata for a skill tool invocation, if it is one."""
    if tool_name not in {LOAD_SKILL_TOOL_NAME, LOAD_SKILL_REFERENCE_TOOL_NAME}:
        return None
    skill_name = tool_args.get("skill_name")
    if not isinstance(skill_name, str):
        return None
    skill = skills_by_name.get(skill_name)
    if skill is None:
        return None

    attributes: dict[str, Any] = get_skill_metadata(skill)
    if tool_name == LOAD_SKILL_TOOL_NAME:
        attributes[SKILL_ORIGIN_ATTRIBUTE] = "model"
        return SkillToolTraceMetadata(
            attributes=attributes,
            capture_output=False,
            skill_name=skill_name,
            is_load=True,
        )

    reference_name = tool_args.get("reference_name")
    if isinstance(reference_name, str):
        attributes[SKILL_RESOURCE_PATH_ATTRIBUTE] = reference_name
    if (load_span_id := state.loaded_span_ids.get(skill_name)) is not None:
        attributes[SKILL_LOAD_SPAN_ID_ATTRIBUTE] = load_span_id
    if (load_tool_call_id := state.loaded_tool_call_ids.get(skill_name)) is not None:
        attributes[SKILL_LOAD_TOOL_CALL_ID_ATTRIBUTE] = load_tool_call_id
    attributes[SKILL_ASSOCIATION_ATTRIBUTE] = "resource_read"
    return SkillToolTraceMetadata(
        attributes=attributes,
        capture_output=False,
        skill_name=skill_name,
        parent_span_context=state.loaded_span_contexts.get(skill_name),
    )


def get_loaded_skill_attributes(state: SkillTraceState) -> dict[str, Any]:
    """Return a single unambiguous skill association for a downstream action."""
    if len(state.loaded_span_ids) != 1:
        return {}
    skill_name, load_span_id = next(iter(state.loaded_span_ids.items()))
    return {
        SKILL_NAME_ATTRIBUTE: skill_name,
        SKILL_ASSOCIATION_ATTRIBUTE: "loaded_context",
        SKILL_LOAD_SPAN_ID_ATTRIBUTE: load_span_id,
        **(
            {SKILL_LOAD_TOOL_CALL_ID_ATTRIBUTE: state.loaded_tool_call_ids[skill_name]}
            if skill_name in state.loaded_tool_call_ids
            else {}
        ),
    }
