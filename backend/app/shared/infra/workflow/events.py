"""Lightweight in-process workflow event bus."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from inspect import isawaitable
from typing import Any, ClassVar, Protocol, runtime_checkable

import structlog

logger = structlog.get_logger()


@runtime_checkable
class WorkflowEvent(Protocol):
    """Protocol implemented by workflow events."""

    event_name: ClassVar[str]
    subject_id: str


EventHandler = Callable[[WorkflowEvent], Awaitable[None] | None]


@dataclass(slots=True)
class LoggedWorkflowEvent:
    """Generic event used for workflow log payloads."""

    event_name: ClassVar[str] = "workflow.logged"

    subject_id: str
    workflow_name: str
    payload: dict[str, Any]


class InProcessEventBus:
    """Simple in-memory event bus for one process."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        """Register one handler for an event name."""

        self._handlers[event_name].append(handler)

    async def publish(self, event: WorkflowEvent) -> None:
        """Publish one event."""

        logger.info(
            "workflow_event_published",
            event_name=event.event_name,
            subject_id=event.subject_id,
        )
        for handler in self._handlers.get(event.event_name, []):
            result = handler(event)
            if isawaitable(result):
                await result

    async def publish_all(self, events: Iterable[WorkflowEvent]) -> None:
        """Publish multiple events in sequence."""

        for event in events:
            await self.publish(event)
