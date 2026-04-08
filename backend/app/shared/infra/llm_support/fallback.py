"""Fallback-aware LLM helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, TypeVar

import structlog

from app.schemas.llm import ChatMessage
from app.shared.infra.model_router import TaskType
from app.shared.infra.tracing import get_llm_trace_context, langsmith_tracing_scope

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

_TIER_FALLBACK_CHAIN: dict[LLMTier, tuple[TaskType, ...]] = {
    "strategic": (TaskType.REASONING, TaskType.DOCGEN, TaskType.DOCGEN_LIGHT),
    "smart": (TaskType.DOCGEN, TaskType.DOCGEN_LIGHT, TaskType.DEFAULT),
    "fast": (TaskType.DOCGEN_LIGHT, TaskType.DEFAULT),
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
    """Run a text or structured completion with a stable fallback chain.

    The wrapper keeps LangSmith metadata aligned across tier downgrades and
    allows planner/docgen code to ask for one logical capability instead of a
    specific single model profile.
    """

    resolved_tier = tier or resolve_llm_tier(task_type)
    chain = _TIER_FALLBACK_CHAIN[resolved_tier]
    trace = get_llm_trace_context()
    last_error: Exception | None = None

    for index, candidate_task_type in enumerate(chain):
        candidate_tier = resolve_llm_tier(candidate_task_type)
        metadata = {
            "llm_tier": resolved_tier,
            "llm_candidate_tier": candidate_tier,
            "llm_candidate_task_type": candidate_task_type.value,
            **dict(extra_metadata or {}),
        }
        if index > 0:
            metadata["llm_fallback_from"] = chain[index - 1].value
            metadata["llm_fallback_to"] = candidate_task_type.value

        try:
            with langsmith_tracing_scope(
                subject=trace.subject,
                build_session_id=trace.build_session_id,
                workflow=trace.workflow,
                lane=trace.lane,
                node=trace.node,
                extra_metadata=metadata,
                extra_tags=[f"tier:{resolved_tier}", f"candidate:{candidate_task_type.value}"],
            ):
                if response_model is not None:
                    return await acompletion_structured(
                        response_model,
                        messages,
                        task_type=candidate_task_type,
                        **kwargs,
                    )
                return await acompletion(
                    messages,
                    task_type=candidate_task_type,
                    **kwargs,
                )
        except Exception as exc:  # pragma: no cover - fallback behavior is integration-heavy
            last_error = exc
            logger.warning(
                "llm_fallback_candidate_failed",
                requested_task_type=task_type.value,
                requested_tier=resolved_tier,
                candidate_task_type=candidate_task_type.value,
                candidate_tier=candidate_tier,
                error=str(exc),
                subject=trace.subject,
                build_session_id=trace.build_session_id,
                workflow=trace.workflow,
                lane=trace.lane,
                node=trace.node,
            )

    assert last_error is not None
    raise last_error


__all__ = ["LLMTier", "acompletion_with_fallback", "resolve_llm_tier"]
