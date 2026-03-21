"""轻量的进程内领域事件总线。"""

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
    """领域事件协议。"""

    event_name: ClassVar[str]
    subject: str


EventHandler = Callable[[WorkflowEvent], Awaitable[None] | None]


@dataclass(slots=True)
class LoggedWorkflowEvent:
    """通用日志事件。"""

    event_name: ClassVar[str] = "workflow.logged"

    subject: str
    workflow_name: str
    payload: dict[str, Any]


class InProcessEventBus:
    """基于内存的轻量事件总线。"""

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        """注册事件处理器。"""

        self._handlers[event_name].append(handler)

    async def publish(self, event: WorkflowEvent) -> None:
        """发布单个事件。"""

        logger.info(
            "workflow_event_published",
            event_name=event.event_name,
            subject=event.subject,
        )
        for handler in self._handlers.get(event.event_name, []):
            result = handler(event)
            if isawaitable(result):
                await result

    async def publish_all(self, events: Iterable[WorkflowEvent]) -> None:
        """批量发布事件。"""

        for event in events:
            await self.publish(event)

