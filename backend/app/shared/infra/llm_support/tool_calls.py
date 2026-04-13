"""Tool-call completion helper built on top of LiteLLM."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import litellm

from app.schemas.llm import ChatMessage
from app.shared.infra.exceptions import LLMTimeoutError
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.observability import langsmith_trace

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
from .observability import (
    _end_langsmith_trace,
    _langsmith_tool_calls,
    _langsmith_trace_kwargs,
    _resolved_trace_model,
)


async def acompletion_with_tools(
    messages: list[ChatMessage],
    *,
    tools: list[dict] | None = None,
    task_type: TaskType = TaskType.DEFAULT,
    **kwargs,
) -> Any:
    """Async completion with tool-call support."""

    context = build_completion_context(task_type)
    last_error: Exception | None = None
    call_started_at = time.monotonic()
    tracked_model = context.profile.model

    async with get_semaphore():
        for attempt in range(1, context.profile.max_retries + 1):
            start = time.monotonic()
            call_kwargs = build_completion_kwargs(
                context=context,
                messages=messages,
                extra_kwargs=kwargs,
            )
            if tools:
                call_kwargs["tools"] = tools
            call_model, provider, tracked_model = _resolved_trace_model(
                call_kwargs,
                context.profile.model,
            )
            logger.info(
                "llm_tools_started",
                attempt=attempt,
                model=tracked_model,
                task_type=context.task_type.value,
                tool_count=len(tools) if tools else 0,
            )
            try:
                with langsmith_trace(
                    name="llm.acompletion_with_tools",
                    run_type="llm",
                    **_langsmith_trace_kwargs(
                        task_type=context.task_type,
                        call_model=call_model,
                        provider=provider,
                        model_name=tracked_model,
                        mode="tools",
                        messages=messages,
                        call_kwargs=call_kwargs,
                        attempt=attempt,
                        tools=tools,
                    ),
                ) as trace_run:
                    response = await asyncio.wait_for(
                        litellm.acompletion(**call_kwargs),
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
                    attempt=attempt,
                    elapsed_s=round(time.monotonic() - start, 2),
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
                logger.warning(
                    "llm_tools_timeout",
                    attempt=attempt,
                    model=tracked_model,
                    task_type=context.task_type.value,
                    timeout_s=context.profile.timeout_s,
                    **trace_log_fields(),
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "llm_tools_failed",
                    attempt=attempt,
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
