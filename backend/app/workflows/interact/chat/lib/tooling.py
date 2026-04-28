"""Tool configuration for the interact chat lane.

Stream nodes use this module to decide which tools are exposed to one turn and
how the agent loop should run. It does not execute tools directly and does not
own the global tool registry.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.shared.infra.agent_loop import AgentLoopConfig
from app.shared.infra.llm_support.routing import LLMCallPurpose
from app.workflows.interact.chat.lib.execution import InteractExecutionMode
from app.workflows.interact.chat.lib.types import RetrievedContext

INTERACT_MODEL_SELECTOR = "primary"
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
    subject_id: str,
    retrieval_results: list[RetrievedContext],
) -> InteractToolPlan:
    """Resolve the bounded tool plan for one turn.

    Today only ``search_kb`` is exposed, but the return shape is intentionally
    list-based so future tools can be added by policy instead of hardcoding
    them in the stream node.
    """

    if execution_mode != InteractExecutionMode.PLAN_EXECUTE:
        return InteractToolPlan(tool_names=[])
    if not subject_id.strip():
        return InteractToolPlan(tool_names=[])

    # When retrieval already found enough material we still allow one search
    # turn; the model can skip it, and the final answer remains token-streamed.
    _ = retrieval_results
    _ = subject_id
    return InteractToolPlan(tool_names=list(DEFAULT_INTERACT_TOOLS))


def build_agent_loop_config(*, tool_plan: InteractToolPlan, subject_id: str) -> AgentLoopConfig:
    """Build the shared AgentLoop configuration for Interact."""

    return AgentLoopConfig(
        max_iterations=tool_plan.max_iterations,
        max_tool_calls_per_turn=tool_plan.max_tool_calls_per_turn,
        tool_timeout_s=tool_plan.tool_timeout_s,
        task_type=LLMCallPurpose.CHAT,
        model=tool_plan.model_selector,
        tool_argument_overrides={"search_kb": {"subject_id": subject_id}},
    )


__all__ = [
    "DEFAULT_INTERACT_TOOLS",
    "INTERACT_MODEL_SELECTOR",
    "InteractToolPlan",
    "build_agent_loop_config",
    "resolve_interact_tool_plan",
]
