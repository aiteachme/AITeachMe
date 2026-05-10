"""Node tracing helpers shared by Profile workflow lanes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.shared.infra.workflow.authoring import WorkflowTraceBinding
from app.shared.infra.workflow.context import WorkflowContext, create_langgraph_dev_context


def _list_field(details: Mapping[str, Any], key: str) -> list[Any]:
    value = details.get(key)
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def route_after_error(state: Mapping[str, Any]) -> str:
    """Route graph execution to failure nodes when state.error is present."""

    return "fail" if state.get("error") else "continue"


def profile_dev_context(workflow_name: str) -> WorkflowContext:
    """Create a LangGraph dev context with the lane inferred from workflow name."""

    context = create_langgraph_dev_context(workflow_name)
    context.metadata["lane"] = workflow_name.rsplit(".", 1)[-1]
    return context


@dataclass(frozen=True, slots=True)
class ProfileNodeTracer:
    """Keep Profile node metadata identical in LangGraph and LangSmith."""

    display_names: Mapping[str, str]
    trace_details: Mapping[str, Mapping[str, Any]]
    timing_fields: Mapping[str, str] | None = None

    def metadata(self, node_key: str) -> dict[str, object]:
        details = self.trace_details[node_key]
        return {
            "node_key": node_key,
            "node_display_name": self.display_names[node_key],
            "node_description": str(details.get("description") or ""),
            "reads": _list_field(details, "reads"),
            "writes": _list_field(details, "writes"),
            "emits": _list_field(details, "emits"),
            "state_inputs": _list_field(details, "input_keys"),
            "state_outputs": _list_field(details, "output_keys"),
        }

    def wrap(self, trace: WorkflowTraceBinding, node_key: str, handler):
        details = self.trace_details[node_key]
        return trace.node(
            handler,
            name=node_key,
            display_name=self.display_names[node_key],
            description=str(details.get("description") or ""),
            input_keys=_list_field(details, "input_keys"),
            output_keys=_list_field(details, "output_keys"),
            timing_field=(self.timing_fields or {}).get(node_key),
            metadata=self.metadata(node_key),
        )


__all__ = [
    "ProfileNodeTracer",
    "profile_dev_context",
    "route_after_error",
]
