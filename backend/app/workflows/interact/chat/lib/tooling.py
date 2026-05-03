"""Tool configuration for the interact chat lane.

Stream nodes use this module to decide which tools are exposed to one turn and
how the agent loop should run. It does not execute tools directly and does not
own the global tool registry.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agent_tools.context import AgentToolContext
from app.agent_tools.policy import AgentToolPolicyRequest, resolve_agent_tool_names
from app.shared.infra.agent_loop import AgentLoopConfig
from app.workflows.interact.chat.lib.execution import InteractExecutionMode
from app.workflows.interact.chat.lib.model_policy import (
    INTERACT_MODEL_SELECTOR,
    InteractModelStep,
    get_interact_model_policy,
    interact_llm_kwargs,
)
from app.workflows.interact.chat.lib.types import RetrievedContext

DEFAULT_INTERACT_TOOLS = ("search_kb",)


@dataclass(frozen=True)
class InteractToolPlan:
    """Resolved tool plan for one chat turn."""

    tool_names: list[str]
    model_selector: str = INTERACT_MODEL_SELECTOR
    max_iterations: int = 3
    max_tool_calls_per_turn: int = 2
    tool_timeout_s: int = 20

    @property
    def uses_tools(self) -> bool:
        return bool(self.tool_names)


def resolve_interact_tool_plan(
    *,
    execution_mode: InteractExecutionMode,
    course_id: str,
    retrieval_results: list[RetrievedContext],
    source: str | None = None,
    allow_write_tools: bool = False,
    approved_tool_names: set[str] | None = None,
) -> InteractToolPlan:
    """Resolve the bounded tool plan for one turn.

    Today only ``search_kb`` is exposed, but the return shape is intentionally
    list-based so future tools can be added by policy instead of hardcoding
    them in the stream node.
    """

    if execution_mode != InteractExecutionMode.PLAN_EXECUTE:
        return InteractToolPlan(tool_names=[])
    _ = retrieval_results
    return InteractToolPlan(
        tool_names=resolve_agent_tool_names(
            AgentToolPolicyRequest(
                source=source,
                course_id=course_id,
                allow_write_tools=allow_write_tools,
                approved_tool_names=frozenset(approved_tool_names or set()),
            )
        )
    )


def build_agent_loop_config(
    *,
    tool_plan: InteractToolPlan,
    course_id: str,
    user_id: str | None = None,
    session_id: str | None = None,
    source: str | None = None,
    attached_file_ids: list[str] | None = None,
    approved_tool_names: set[str] | None = None,
    model_selector: str | None = None,
    extra_metadata: dict[str, object] | None = None,
) -> AgentLoopConfig:
    """Build the shared AgentLoop configuration for Interact."""

    return AgentLoopConfig(
        max_iterations=tool_plan.max_iterations,
        max_tool_calls_per_turn=tool_plan.max_tool_calls_per_turn,
        tool_timeout_s=tool_plan.tool_timeout_s,
        task_type=get_interact_model_policy(InteractModelStep.RESPONSE_STREAM).call_purpose,
        model=model_selector or tool_plan.model_selector,
        llm_kwargs=interact_llm_kwargs(InteractModelStep.RESPONSE_STREAM),
        tool_context=AgentToolContext(
            user_id=user_id,
            course_id=course_id,
            session_id=session_id,
            source=source,
            attached_file_ids=tuple(attached_file_ids or ()),
            approved_tool_names=frozenset(approved_tool_names or set()),
        ),
        approved_tool_names=set(approved_tool_names or set()),
        extra_metadata=dict(extra_metadata or {}),
    )


__all__ = [
    "DEFAULT_INTERACT_TOOLS",
    "INTERACT_MODEL_SELECTOR",
    "InteractToolPlan",
    "build_agent_loop_config",
    "resolve_interact_tool_plan",
]
