"""Business-friendly LLM facade over the canonical ``llm_support`` package."""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, TypeVar

from app.schemas.llm import ChatMessage
from app.shared.infra.llm_support import acompletion, acompletion_stream, acompletion_structured
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.observability.trace import llm_trace_scope

from .context import InfraContext

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class LLMTextResult:
    """Text completion facade result."""

    content: str
    task_type: str


async def call_llm_text(
    ctx: InfraContext,
    messages: list[ChatMessage],
    *,
    task_type: TaskType = TaskType.DEFAULT,
    model: str | None = None,
    **kwargs,
) -> LLMTextResult:
    """Call the configured text model with ambient trace context."""

    with llm_trace_scope(
        subject=ctx.subject,
        build_session_id=ctx.build_session_id,
        workflow=ctx.workflow,
        lane=ctx.lane,
        node=ctx.node,
    ):
        content = await acompletion(messages, task_type=task_type, model=model, **kwargs)
    return LLMTextResult(content=content, task_type=task_type.value)


async def call_llm_structured(
    ctx: InfraContext,
    response_model: type[T],
    messages: list[ChatMessage],
    *,
    task_type: TaskType = TaskType.DEFAULT,
    model: str | None = None,
    **kwargs,
) -> T:
    """Call the configured model and parse the response into ``response_model``."""

    with llm_trace_scope(
        subject=ctx.subject,
        build_session_id=ctx.build_session_id,
        workflow=ctx.workflow,
        lane=ctx.lane,
        node=ctx.node,
    ):
        return await acompletion_structured(response_model, messages, task_type=task_type, model=model, **kwargs)


async def stream_llm_text(
    ctx: InfraContext,
    messages: list[ChatMessage],
    *,
    task_type: TaskType = TaskType.DEFAULT,
    model: str | None = None,
    **kwargs,
) -> AsyncIterator[str]:
    """Stream text chunks from the configured model."""

    with llm_trace_scope(
        subject=ctx.subject,
        build_session_id=ctx.build_session_id,
        workflow=ctx.workflow,
        lane=ctx.lane,
        node=ctx.node,
    ):
        async for chunk in acompletion_stream(messages, task_type=task_type, model=model, **kwargs):
            yield chunk


__all__ = [
    "LLMTextResult",
    "call_llm_structured",
    "call_llm_text",
    "stream_llm_text",
]
