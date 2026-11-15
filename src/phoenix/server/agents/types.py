from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from pydantic_ai import DeferredToolRequests

from phoenix.server.agents.context import ResolvedContexts
from phoenix.server.agents.skill_tracing import SkillTraceState

AgentOutput: TypeAlias = str | DeferredToolRequests


@dataclass
class AgentDependencies:
    contexts: ResolvedContexts
    edit_permission: Literal["manual", "bypass"] = "manual"
    is_viewer: bool = False
    skill_trace_state: SkillTraceState = field(default_factory=SkillTraceState)
