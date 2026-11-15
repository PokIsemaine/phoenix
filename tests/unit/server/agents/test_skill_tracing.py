from __future__ import annotations

import json
from pathlib import Path

from phoenix.server.agents.skill_tracing import (
    SKILL_APPLIED_ATTRIBUTE,
    SKILL_HASH_ATTRIBUTE,
    SKILL_LOAD_SPAN_ID_ATTRIBUTE,
    SKILL_NAME_ATTRIBUTE,
    SKILL_ORIGIN_ATTRIBUTE,
    SKILL_RESOURCE_PATH_ATTRIBUTE,
    SkillTraceState,
    get_applied_skill_attributes,
    get_available_skills_attribute,
    get_skill_metadata,
    get_skill_tool_trace_metadata,
)
from phoenix.server.mcp.skills import Skill


def _skill(tmp_path: Path) -> Skill:
    directory = tmp_path / "demo-skill"
    directory.mkdir()
    return Skill(
        name="demo-skill",
        description="A demo skill.",
        summary="Demo",
        text="---\nname: demo-skill\ndescription: A demo skill.\n---\nInstructions",
        path=directory,
    )


def test_skill_metadata_is_stable_and_does_not_include_body(tmp_path: Path) -> None:
    skill = _skill(tmp_path)
    metadata = get_skill_metadata(skill)

    assert metadata[SKILL_NAME_ATTRIBUTE] == "demo-skill"
    assert metadata[SKILL_HASH_ATTRIBUTE]
    assert "Instructions" not in json.dumps(metadata)


def test_available_catalog_contains_identity_metadata_only(tmp_path: Path) -> None:
    skill = _skill(tmp_path)
    catalog = json.loads(get_available_skills_attribute((skill,)))

    assert catalog == [
        {
            "hash": get_skill_metadata(skill)[SKILL_HASH_ATTRIBUTE],
            "name": "demo-skill",
            "source": "external",
            "version": get_skill_metadata(skill)[SKILL_HASH_ATTRIBUTE],
        }
    ]
    assert "Instructions" not in json.dumps(catalog)


def test_skill_tool_metadata_distinguishes_load_and_resource_read(tmp_path: Path) -> None:
    skill = _skill(tmp_path)
    state = SkillTraceState()
    skills = {skill.name: skill}

    load = get_skill_tool_trace_metadata(
        tool_name="load_skill",
        tool_args={"skill_name": skill.name},
        skills_by_name=skills,
        state=state,
    )
    assert load is not None
    assert load.is_load
    assert load.capture_output is False
    assert load.attributes[SKILL_ORIGIN_ATTRIBUTE] == "model"

    state.loaded_span_ids[skill.name] = "span-1"
    resource = get_skill_tool_trace_metadata(
        tool_name="load_skill_reference",
        tool_args={"skill_name": skill.name, "reference_name": "references/example.md"},
        skills_by_name=skills,
        state=state,
    )
    assert resource is not None
    assert resource.attributes[SKILL_RESOURCE_PATH_ATTRIBUTE] == "references/example.md"
    assert resource.attributes[SKILL_LOAD_SPAN_ID_ATTRIBUTE] == "span-1"
    assert resource.attributes[SKILL_APPLIED_ATTRIBUTE] is True


def test_downstream_action_is_linked_when_one_skill_is_loaded() -> None:
    attributes = get_applied_skill_attributes(SkillTraceState(loaded_span_ids={"demo": "span-1"}))

    assert attributes == {
        SKILL_NAME_ATTRIBUTE: "demo",
        SKILL_APPLIED_ATTRIBUTE: True,
        SKILL_LOAD_SPAN_ID_ATTRIBUTE: "span-1",
    }
