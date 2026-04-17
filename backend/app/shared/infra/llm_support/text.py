"""Text completion helper built on top of LiteLLM."""

from __future__ import annotations

import asyncio
import time

from app.schemas.llm import ChatMessage
from app.shared.infra.exceptions import LLMTimeoutError
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.observability.trace import langsmith_trace

from .litellm_loader import load_litellm
from .common import (
    build_completion_context,
    build_completion_kwargs,
    extract_usage,
    get_semaphore,
    logger,
    raise_last_error,
    request_timeout_s,
    trace_log_fields,
    track_call,
)
from .observability import _end_langsmith_trace, _langsmith_trace_kwargs, _resolved_trace_model

litellm = load_litellm()


async def acompletion(
    messages: list[ChatMessage],
    *,
    task_type: TaskType = TaskType.DEFAULT,
    model: str | None = None,
    **kwargs,
) -> str:
    """Async text completion."""

    context = build_completion_context(
        task_type,
        model=model,
    )
    last_error: Exception | None = None
    call_started_at = time.monotonic()
    tracked_model = context.model

    async with get_semaphore():
        for attempt in range(1, context.profile.max_retries + 1):
            start = time.monotonic()
            call_kwargs = build_completion_kwargs(
                context=context,
                messages=messages,
                extra_kwargs=kwargs,
            )
            call_model, provider, tracked_model = _resolved_trace_model(
                call_kwargs,
                context.model,
            )
            logger.info(
                "llm_completion_started",
                attempt=attempt,
                model=tracked_model,
                task_type=context.task_type.value,
                timeout_s=context.profile.timeout_s,
            )
            try:
                with langsmith_trace(
                    name="LLM：文本生成",
                    run_type="llm",
                    **_langsmith_trace_kwargs(
                        task_type=context.task_type,
                        call_model=call_model,
                        provider=provider,
                        model_name=tracked_model,
                        mode="text",
                        messages=messages,
                        call_kwargs=call_kwargs,
                        attempt=attempt,
                    ),
                ) as trace_run:
                    response = await asyncio.wait_for(
                        litellm.acompletion(**call_kwargs),
                        timeout=request_timeout_s(context.profile.timeout_s),
                    )
                    prompt_t, completion_t, total_t = extract_usage(response)
                    content = response.choices[0].message.content or ""
                    _end_langsmith_trace(
                        trace_run,
                        text=content,
                        prompt_tokens=prompt_t,
                        completion_tokens=completion_t,
                        total_tokens=total_t,
                    )
                logger.info(
                    "llm_completion_complete",
                    attempt=attempt,
                    elapsed_s=round(time.monotonic() - start, 2),
                    model=tracked_model,
                    task_type=context.task_type.value,
                )
                track_call(
                    task_type=context.task_type,
                    model=tracked_model,
                    start=call_started_at,
                    success=True,
                    prompt_tokens=prompt_t,
                    completion_tokens=completion_t,
                    total_tokens=total_t,
                )
                return content
            except asyncio.TimeoutError:
                last_error = LLMTimeoutError(timeout_s=context.profile.timeout_s)
                logger.warning(
                    "llm_completion_timeout",
                    attempt=attempt,
                    elapsed_s=round(time.monotonic() - start, 2),
                    model=tracked_model,
                    task_type=context.task_type.value,
                    timeout_s=context.profile.timeout_s,
                    **trace_log_fields(),
                )
            except asyncio.CancelledError:
                last_error = asyncio.CancelledError()
                logger.info(
                    "llm_completion_cancelled",
                    attempt=attempt,
                    elapsed_s=round(time.monotonic() - start, 2),
                    model=tracked_model,
                    task_type=context.task_type.value,
                    **trace_log_fields(),
                )
                track_call(
                    task_type=context.task_type,
                    model=tracked_model,
                    start=call_started_at,
                    success=False,
                    error="cancelled",
                )
                raise
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "llm_completion_failed",
                    attempt=attempt,
                    elapsed_s=round(time.monotonic() - start, 2),
                    model=tracked_model,
                    task_type=context.task_type.value,
                    error=str(exc),
                    **trace_log_fields(),
                )

            if attempt < context.profile.max_retries:
                await asyncio.sleep(attempt * 2)

    track_call(
        task_type=context.task_type,
        model=tracked_model,
        start=call_started_at,
        success=False,
        error=str(last_error),
    )
    raise_last_error(last_error)
