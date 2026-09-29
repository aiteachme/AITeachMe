"""Thin LLM port for declarative question-type runtimes.

Question-type code can depend on this small interface without owning model
selection, retries, timeouts, tracing, rate limits, or provider clients. All
of those concerns remain in the shared ``llm_support`` infrastructure.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypeVar

from app.schemas.llm import ChatMessage
from app.shared.infra.llm_support import acompletion_with_fallback


T = TypeVar("T")


async def llm(
    messages: Sequence[ChatMessage],
    *,
    response_model: type[T] | None = None,
    task_type: object | None = None,
    model: str | None = None,
    extra_metadata: Mapping[str, Any] | None = None,
    **completion_kwargs: Any,
) -> str | T:
    """Call the platform LLM helper through one stable runtime-facing port.

    This function deliberately contains no retry loop, scheduler, limiter, or
    provider selection logic. ``acompletion_with_fallback`` remains the single
    owner of those behaviours; ``run_llm_tasks`` remains the owner of batch
    scheduling.
    """

    return await acompletion_with_fallback(
        list(messages),
        response_model=response_model,
        task_type=task_type,
        model=model,
        extra_metadata=extra_metadata,
        **completion_kwargs,
    )


__all__ = ["llm"]
