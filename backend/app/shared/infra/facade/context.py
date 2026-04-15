"""Shared infra facade context.

This module intentionally contains no business workflow state. It only carries
cross-cutting runtime metadata used by infra capabilities such as LLM calls,
retrieval, tools, parsing, evals, and observability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class InfraContext:
    """Cross-layer context for infra facade calls."""

    subject: str = ""
    user_id: str = ""
    workflow: str = ""
    lane: str = ""
    node: str = ""
    build_session_id: str = ""
    request_id: str = ""
    permissions: frozenset[str] = field(default_factory=frozenset)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def with_node(self, node: str, *, lane: str | None = None) -> "InfraContext":
        """Return a copy scoped to a nested infra node."""

        return InfraContext(
            subject=self.subject,
            user_id=self.user_id,
            workflow=self.workflow,
            lane=self.lane if lane is None else lane,
            node=node,
            build_session_id=self.build_session_id,
            request_id=self.request_id,
            permissions=self.permissions,
            metadata=dict(self.metadata),
        )

    def trace_metadata(self, **extra: Any) -> dict[str, Any]:
        """Build sanitized metadata payload for trace helpers."""

        payload = dict(self.metadata)
        if self.user_id:
            payload.setdefault("user_id", self.user_id)
        if self.request_id:
            payload.setdefault("request_id", self.request_id)
        payload.update({key: value for key, value in extra.items() if value not in (None, "", [], {})})
        return payload


@dataclass(frozen=True, slots=True)
class FacadeWorkflowTraceContext:
    """Minimal protocol-compatible workflow context for traced executions."""

    workflow_name: str
    subject: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


def build_infra_context(
    *,
    subject: str = "",
    user_id: str = "",
    workflow: str = "",
    lane: str = "",
    node: str = "",
    build_session_id: str = "",
    request_id: str = "",
    permissions: set[str] | frozenset[str] | list[str] | tuple[str, ...] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> InfraContext:
    """Build a normalized infra context."""

    return InfraContext(
        subject=str(subject or "").strip(),
        user_id=str(user_id or "").strip(),
        workflow=str(workflow or "").strip(),
        lane=str(lane or "").strip(),
        node=str(node or "").strip(),
        build_session_id=str(build_session_id or "").strip(),
        request_id=str(request_id or "").strip(),
        permissions=frozenset(str(item).strip() for item in (permissions or []) if str(item).strip()),
        metadata=dict(metadata or {}),
    )


def workflow_trace_context(ctx: InfraContext) -> FacadeWorkflowTraceContext:
    """Project an ``InfraContext`` into the traced-execution protocol."""

    return FacadeWorkflowTraceContext(
        workflow_name=ctx.workflow,
        subject=ctx.subject,
        metadata=ctx.trace_metadata(lane=ctx.lane, node=ctx.node),
    )


__all__ = [
    "FacadeWorkflowTraceContext",
    "InfraContext",
    "build_infra_context",
    "workflow_trace_context",
]
