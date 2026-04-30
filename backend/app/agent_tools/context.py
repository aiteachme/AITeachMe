"""Runtime context injected into agent tool calls."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentToolContext:
    """Request-scoped values that must stay hidden from the LLM schema."""

    user_id: str | None = None
    course_id: str | None = None
    session_id: str | None = None
    source: str | None = None
    attached_file_ids: tuple[str, ...] = field(default_factory=tuple)
    approved_tool_names: frozenset[str] = field(default_factory=frozenset)
    background_task_registry: Any | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    def tool_arguments_for(
        self,
        *,
        tool_name: str,
        hidden_args: list[str],
    ) -> dict[str, Any]:
        del tool_name
        values: dict[str, Any] = {}
        for name in hidden_args:
            if hasattr(self, name):
                value = getattr(self, name)
            else:
                value = self.extra.get(name)
            if value is not None:
                values[name] = value
        return values

    def is_tool_approved(self, tool_name: str) -> bool:
        return tool_name in self.approved_tool_names
