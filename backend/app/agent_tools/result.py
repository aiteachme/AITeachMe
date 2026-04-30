"""Shared return envelopes for agent tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ClientAction:
    """A structured action that a client may perform after a tool call."""

    type: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "payload": dict(self.payload)}


@dataclass(frozen=True)
class AgentToolResult:
    """Stable envelope for future tools that need structured side effects."""

    ok: bool
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    client_actions: list[ClientAction] = field(default_factory=list)
    audit: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "message": self.message,
            "data": dict(self.data),
            "client_actions": [action.to_dict() for action in self.client_actions],
            "audit": dict(self.audit),
        }
