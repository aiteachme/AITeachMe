"""Fallback-aware LLM helpers.

AITeachMe uses a three-tier model strategy to balance reasoning depth,
output quality, and throughput cost:

- **reason**  – 推理模型：deep chain-of-thought reasoning, highest accuracy.
                Used for tasks that require multi-step logical analysis
                (e.g. retrieval query planning, curriculum strategy).
- **primary** – 常用模型：the everyday workhorse model with balanced
                quality and cost. Used for content creation, question
                generation, grading, interactive chat, and vision OCR.
- **fast**    – 快速模型：lightweight, high-throughput, low-cost model.
                Used for batch extraction, classification, summarisation,
                and auxiliary annotation tasks.

Business code selects a ``TaskType``; this module maps it to the
appropriate tier and provides a transparent fallback chain so that a
temporary model outage degrades gracefully instead of failing hard.
"""

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

LLMTier = Literal["reason", "primary", "fast"]
T = TypeVar("T")

# ── TaskType → Tier mapping ────────────────────────────────────────
#
#   reason  : REASONING
#   primary : DOCGEN, GENERATE, GRADE, CHAT, VISION, DEFAULT
#   fast    : DOCGEN_LIGHT, EXTRACT, SUMMARIZE, CLASSIFY
#
# Key design decision: EXTRACT uses the *fast* tier because knowledge-
# graph extraction is a high-volume batch task (hundreds of LLM calls
# per digest run); routing it through the primary model is wasteful.

_TASK_TO_TIER: dict[TaskType, LLMTier] = {
    TaskType.REASONING: "reason",
    TaskType.DOCGEN: "primary",
    TaskType.DOCGEN_LIGHT: "fast",
    TaskType.EXTRACT: "fast",
    TaskType.GENERATE: "primary",
    TaskType.GRADE: "primary",
    TaskType.CHAT: "primary",
    TaskType.SUMMARIZE: "fast",
    TaskType.CLASSIFY: "fast",
    TaskType.VISION: "primary",
    TaskType.DEFAULT: "primary",
}

# ── Fallback chains ────────────────────────────────────────────────
# When a tier's model fails, we try progressively cheaper alternatives.

_TIER_FALLBACK_CHAIN: dict[LLMTier, tuple[TaskType, ...]] = {
    "reason": (TaskType.REASONING, TaskType.DOCGEN, TaskType.DOCGEN_LIGHT),
    "primary": (TaskType.DOCGEN, TaskType.DOCGEN_LIGHT, TaskType.DEFAULT),
    "fast": (TaskType.DOCGEN_LIGHT, TaskType.DEFAULT),
}


def resolve_llm_tier(task_type: TaskType) -> LLMTier:
    """Resolve the default LLM tier for one task type."""

    return _TASK_TO_TIER.get(task_type, "primary")


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
    from app.shared.infra.tracing import get_llm_trace_context, langsmith_tracing_scope

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
