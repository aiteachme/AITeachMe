"""Tool-call completion helper built on top of LiteLLM."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Any

from app.schemas.llm import ChatMessage
from app.shared.infra.exceptions import LLMTimeoutError
from app.shared.infra.observability.trace import langsmith_trace

from .common import (
    build_completion_contexts,
    effective_call_timeout_s,
    effective_max_retries,
    extract_usage,
    get_llm_concurrency_limiter,
    logger,
    log_attempt_cancelled,
    log_attempt_failed,
    log_attempt_started,
    log_attempt_timeout,
    prepare_completion_attempt,
    raise_last_error,
    context_request_timeout_s,
    sleep_before_retry,
    track_call,
)
from .litellm_loader import load_litellm
from .native_tools import without_provider_native_tools
from .observability import (
    _end_langsmith_trace,
    _langsmith_tool_calls,
    _langsmith_trace_kwargs,
)


async def acompletion_with_tools(
    messages: list[ChatMessage],
    *,
    tools: list[dict] | None = None,
    task_type: object | None = None,
    model: str | None = None,
    extra_metadata: Mapping[str, Any] | None = None,
    **kwargs,
) -> Any:
    """Async completion with tool-call support."""

    litellm = load_litellm()
    contexts = build_completion_contexts(
        task_type=task_type,
        model=model,
    )
    primary_context = contexts[0]
    last_error: Exception | None = None
    call_started_at = time.monotonic()
    tracked_model = primary_context.model
    max_retries = effective_max_retries(primary_context, kwargs)
    attempt_number = 0

    async with get_llm_concurrency_limiter():
        for retry_round in range(1, max_retries + 1):
            for context in contexts:
                attempt_number += 1
                prepared = prepare_completion_attempt(
                    context=context,
                    messages=messages,
                    extra_kwargs=without_provider_native_tools(kwargs),
                    attempt=attempt_number,
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
                            endpoint_role=context.endpoint_role,
                            model_selector=context.model_selector,
                            tools=tools,
                            extra_metadata=extra_metadata,
                        ),
                    ) as trace_run:
                        response = await asyncio.wait_for(
                            litellm.acompletion(**prepared.call_kwargs),
                            timeout=context_request_timeout_s(context, prepared.call_kwargs),
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
                        task_type=context.task_type,
                        endpoint_role=context.endpoint_role,
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
                    last_error = LLMTimeoutError(
                        timeout_s=effective_call_timeout_s(context, prepared.call_kwargs)
                    )
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

            if retry_round < max_retries:
                await sleep_before_retry(retry_round)

    track_call(
        task_type=primary_context.task_type,
        model=tracked_model,
        start=call_started_at,
        success=False,
        error=str(last_error),
    )
    raise_last_error(last_error)
