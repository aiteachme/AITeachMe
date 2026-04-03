"""Kernel-level event primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from app.shared.kernel.time import utcnow


@dataclass(slots=True)
class DomainEvent:
    """Minimal domain event envelope."""

    name: str
    aggregate_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=utcnow)


class EventPublisher(Protocol):
    """Contract for dispatching domain events."""

    async def publish(self, event: DomainEvent) -> None:
        """Publish one event."""

