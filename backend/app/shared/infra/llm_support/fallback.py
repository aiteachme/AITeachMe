"""Fallback-aware LLM helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, TypeVar

import structlog

from app.schemas.llm import ChatMessage
from app.shared.infra.llm_support.routing import TaskType
# NOTE: tracing imports are deferred to function scope to avoid
# circular import: tracing → llm_support/__init__ → fallback → tracing

from .structured_calls import acompletion_structured
from .text import acompletion

logger = structlog.get_logger(__name__)

LLMTier = Literal["strategic", "smart", "fast"]
T = TypeVar("T")

_TASK_TO_TIER: dict[TaskType, LLMTier] = {
    TaskType.REASONING: "strategic",
    TaskType.DOCGEN: "smart",
    TaskType.DOCGEN_LIGHT: "fast",
    TaskType.EXTRACT: "smart",
    TaskType.GENERATE: "smart",
    TaskType.GRADE: "smart",
    TaskType.CHAT: "smart",
    TaskType.SUMMARIZE: "fast",
    TaskType.CLASSIFY: "fast",
    TaskType.VISION: "smart",
    TaskType.DEFAULT: "smart",
}

def resolve_llm_tier(task_type: TaskType) -> LLMTier:
    """Resolve the default LLM tier for one task type."""

    return _TASK_TO_TIER.get(task_type, "smart")


async def acompletion_with_fallback(
    messages: list[ChatMessage],
    *,
    task_type: TaskType = TaskType.DEFAULT,
    tier: LLMTier | None = None,
    response_model: type[T] | None = None,
    extra_metadata: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> str | T:
    """Run one text or structured completion with strict failure semantics."""

    resolved_tier = tier or resolve_llm_tier(task_type)
    from app.shared.infra.tracing import get_llm_trace_context, langsmith_tracing_scope

    trace = get_llm_trace_context()
    metadata = {
        "llm_tier": resolved_tier,
        "llm_candidate_tier": resolved_tier,
        "llm_candidate_task_type": task_type.value,
        "llm_strict_mode": True,
        **dict(extra_metadata or {}),
    }

    try:
        with langsmith_tracing_scope(
            subject=trace.subject,
            build_session_id=trace.build_session_id,
            workflow=trace.workflow,
            lane=trace.lane,
            node=trace.node,
            extra_metadata=metadata,
            extra_tags=[f"tier:{resolved_tier}", f"candidate:{task_type.value}"],
        ):
            if response_model is not None:
                return await acompletion_structured(
                    response_model,
                    messages,
                    task_type=task_type,
                    **kwargs,
                )
            return await acompletion(
                messages,
                task_type=task_type,
                **kwargs,
            )
    except Exception as exc:  # pragma: no cover - integration-heavy behavior
        logger.warning(
            "llm_primary_call_failed",
            requested_task_type=task_type.value,
            requested_tier=resolved_tier,
            error=str(exc),
            subject=trace.subject,
            build_session_id=trace.build_session_id,
            workflow=trace.workflow,
            lane=trace.lane,
            node=trace.node,
        )
        raise


__all__ = ["LLMTier", "acompletion_with_fallback", "resolve_llm_tier"]
