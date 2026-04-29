"""Strict LLM helper wrapper with trace metadata."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

import structlog

from app.schemas.llm import ChatMessage
from app.shared.infra.llm_support.common import normalize_model_selector
from app.shared.infra.llm_support.common import resolve_call_purpose
from app.shared.infra.llm_support.routing import LLMCallPurpose

from .structured_calls import acompletion_structured
from .text import acompletion

logger = structlog.get_logger(__name__)

T = TypeVar("T")


async def acompletion_with_fallback(
    messages: list[ChatMessage],
    *,
    call_purpose: LLMCallPurpose | None = None,
    task_type: LLMCallPurpose | None = None,
    model: str | None = None,
    response_model: type[T] | None = None,
    extra_metadata: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> str | T:
    """Run one text or structured completion with strict failure semantics."""

    resolved_purpose = resolve_call_purpose(call_purpose=call_purpose, task_type=task_type)
    model_selector = normalize_model_selector(model) or "primary"
    from app.shared.infra.observability.trace import (
        get_llm_trace_context,
        langsmith_tracing_scope,
    )

    trace = get_llm_trace_context()
    metadata = {
        "llm_model_selector": model_selector,
        "llm_call_purpose": resolved_purpose.value,
        "llm_strict_mode": True,
        **dict(extra_metadata or {}),
    }

    try:
        with langsmith_tracing_scope(
            course_id=trace.course_id,
            build_session_id=trace.build_session_id,
            workflow=trace.workflow,
            lane=trace.lane,
            node=trace.node,
            extra_metadata=metadata,
        ):
            if response_model is not None:
                return await acompletion_structured(
                    response_model,
                    messages,
                    call_purpose=resolved_purpose,
                    model=model_selector,
                    extra_metadata=metadata,
                    **kwargs,
                )
            return await acompletion(
                messages,
                call_purpose=resolved_purpose,
                model=model_selector,
                extra_metadata=metadata,
                **kwargs,
            )
    except Exception as exc:  # pragma: no cover - integration-heavy behavior
        logger.warning(
            "llm_call_failed",
            requested_call_purpose=resolved_purpose.value,
            requested_model=model_selector,
            error=str(exc),
            course_id=trace.course_id,
            build_session_id=trace.build_session_id,
            workflow=trace.workflow,
            lane=trace.lane,
            node=trace.node,
        )
        raise


__all__ = ["acompletion_with_fallback"]
