"""Tool-call completion helper built on top of LiteLLM."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.schemas.llm import ChatMessage
from app.shared.infra.exceptions import LLMTimeoutError
from app.shared.infra.llm_support.routing import LLMCallPurpose
from app.shared.infra.observability.trace import langsmith_trace

from .litellm_loader import load_litellm
from .common import (
    build_completion_context,
    extract_usage,
    get_semaphore,
    logger,
    log_attempt_cancelled,
    log_attempt_failed,
    log_attempt_started,
    log_attempt_timeout,
    prepare_completion_attempt,
    raise_last_error,
    request_timeout_s,
    sleep_before_retry,
    track_call,
)
from .observability import (
    _end_langsmith_trace,
    _langsmith_tool_calls,
    _langsmith_trace_kwargs,
)

litellm = load_litellm()


async def acompletion_with_tools(
    messages: list[ChatMessage],
    *,
    tools: list[dict] | None = None,
    call_purpose: LLMCallPurpose | None = None,
    task_type: LLMCallPurpose | None = None,
    model: str | None = None,
    **kwargs,
) -> Any:
    """Async completion with tool-call support."""

    context = build_completion_context(
        task_type=task_type,
        call_purpose=call_purpose,
        model=model,
    )
    last_error: Exception | None = None
    call_started_at = time.monotonic()
    tracked_model = context.model

    async with get_semaphore():
        for attempt in range(1, context.profile.max_retries + 1):
            prepared = prepare_completion_attempt(
                context=context,
                messages=messages,
                extra_kwargs=kwargs,
                attempt=attempt,
                override_kwargs={"tools": tools} if tools else None,
            )
            tracked_model = prepared.tracked_model
            log_attempt_started(
                "llm_tools_started",
                attempt=prepared,
                context=context,
                extra={"tool_count": len(tools) if tools else 0},
            )
            try:
                with langsmith_trace(
                    name="LLM：工具调用",
                    run_type="llm",
                    **_langsmith_trace_kwargs(
                        task_type=context.task_type,
                        call_model=prepared.call_model,
                        provider=prepared.provider,
                        model_name=tracked_model,
                        mode="tools",
                        messages=messages,
                        call_kwargs=prepared.call_kwargs,
                        attempt=prepared.attempt,
                        tools=tools,
                    ),
                ) as trace_run:
                    response = await asyncio.wait_for(
                        litellm.acompletion(**prepared.call_kwargs),
                        timeout=request_timeout_s(context.profile.timeout_s),
                    )
                    prompt_t, completion_t, total_t = extract_usage(response)
                    message = response.choices[0].message
                    _end_langsmith_trace(
                        trace_run,
                        text=message.content or "",
                        tool_calls=_langsmith_tool_calls(message),
                        prompt_tokens=prompt_t,
                        completion_tokens=completion_t,
                        total_tokens=total_t,
                    )
                logger.info(
                    "llm_tools_complete",
                    attempt=prepared.attempt,
                    elapsed_s=round(time.monotonic() - prepared.started_at, 2),
                    model=tracked_model,
                    task_type=context.task_type.value,
                    has_tool_calls=bool(getattr(response.choices[0].message, "tool_calls", None)),
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
                return response
            except asyncio.TimeoutError:
                last_error = LLMTimeoutError(timeout_s=context.profile.timeout_s)
                log_attempt_timeout(
                    "llm_tools_timeout",
                    attempt=prepared,
                    context=context,
                )
            except asyncio.CancelledError:
                last_error = asyncio.CancelledError()
                log_attempt_cancelled(
                    "llm_tools_cancelled",
                    attempt=prepared,
                    context=context,
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
                log_attempt_failed(
                    "llm_tools_failed",
                    attempt=prepared,
                    context=context,
                    error=exc,
                )

            if attempt < context.profile.max_retries:
                await sleep_before_retry(attempt)

    track_call(
        task_type=context.task_type,
        model=tracked_model,
        start=call_started_at,
        success=False,
        error=str(last_error),
    )
    raise_last_error(last_error)
