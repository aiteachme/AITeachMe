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
    completion_context_groups,
    effective_call_timeout_s,
    effective_endpoint_group_max_retries,
    extract_usage,
    get_llm_concurrency_limiter,
    logger,
    log_attempt_cancelled,
    log_attempt_failed,
    log_attempt_started,
    log_attempt_timeout,
    prepare_completion_attempt,
    pop_overall_timeout_s,
    raise_last_error,
    context_request_timeout_s,
    should_advance_to_fallback,
    should_try_endpoint_fallback,
    sleep_before_retry,
    track_call,
    wait_for_overall_timeout,
)
from .litellm_loader import load_litellm
from .native_tools import without_provider_native_tools
from .observability import (
    _end_langsmith_trace,
    _langsmith_tool_calls,
    _langsmith_trace_kwargs,
    llm_api_mode_outputs,
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

    overall_timeout_s = pop_overall_timeout_s(kwargs)
    return await wait_for_overall_timeout(
        _acompletion_with_tools_impl(
            messages,
            tools=tools,
            task_type=task_type,
            model=model,
            extra_metadata=extra_metadata,
            kwargs=kwargs,
        ),
        overall_timeout_s,
    )


async def _acompletion_with_tools_impl(
    messages: list[ChatMessage],
    *,
    tools: list[dict] | None,
    task_type: object | None,
    model: str | None,
    extra_metadata: Mapping[str, Any] | None,
    kwargs: dict[str, Any],
) -> Any:
    litellm = load_litellm()
    contexts = build_completion_contexts(
        task_type=task_type,
        model=model,
    )
    primary_context = contexts[0]
    last_error: Exception | None = None
    call_started_at = time.monotonic()
    tracked_model = primary_context.model
    attempt_number = 0
    has_fallback_endpoints = any(context.endpoint_role == "fallback" for context in contexts)

    async with get_llm_concurrency_limiter().slot() as lease:
        for group_index, context_group in enumerate(completion_context_groups(contexts)):
            if (
                group_index > 0
                and context_group[0].endpoint_role == "fallback"
                and not should_try_endpoint_fallback(last_error)
            ):
                logger.warning(
                    "llm_tools_endpoint_fallback_skipped_non_endpoint_error",
                    task_type=primary_context.task_type,
                    model=tracked_model,
                    error=str(last_error),
                    error_type=last_error.__class__.__name__ if last_error is not None else "",
                )
                break
            group_max_retries = effective_endpoint_group_max_retries(context_group[0], kwargs)
            for retry_round in range(1, group_max_retries + 1):
                for context in context_group:
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
                        extra={
                            "tool_count": len(tools) if tools else 0,
                            "api_mode": "chat_completions",
                        },
                    )
                    try:
                        trace_metadata = {
                            **dict(extra_metadata or {}),
                            "llm_requested_api_mode": str(
                                kwargs.get("api_mode") or context.settings.llm.api_mode
                            ),
                            "llm_api_mode_route_reason": "project_function_tools_chat_completions",
                        }
                        with langsmith_trace(
                            name="LLM：工具调用",
                            run_type="llm",
                            **_langsmith_trace_kwargs(
                                task_type=context.task_type,
                                call_model=prepared.call_model,
                                provider=prepared.provider,
                                model_name=tracked_model,
                                mode="tools_chat_completions",
                                messages=messages,
                                call_kwargs=prepared.call_kwargs,
                                attempt=prepared.attempt,
                                endpoint_role=context.endpoint_role,
                                model_selector=context.model_selector,
                                tools=tools,
                                extra_metadata=trace_metadata,
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
                                extra_outputs=llm_api_mode_outputs(
                                    initial_api_mode="chat_completions",
                                    final_api_mode="chat_completions",
                                    final_route_reason="project_function_tools_chat_completions",
                                ),
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
                            api_mode="chat_completions",
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

                if should_advance_to_fallback(
                    context_group,
                    has_fallback_endpoints=has_fallback_endpoints,
                    error=last_error,
                ):
                    logger.info(
                        "llm_tools_primary_retries_skipped_for_endpoint_fallback",
                        task_type=primary_context.task_type,
                        model=tracked_model,
                        error_type=last_error.__class__.__name__ if last_error is not None else "",
                    )
                    break
                if retry_round < group_max_retries:
                    await sleep_before_retry(retry_round, error=last_error, lease=lease)

    track_call(
        task_type=primary_context.task_type,
        model=tracked_model,
        start=call_started_at,
        success=False,
        error=str(last_error),
    )
    raise_last_error(last_error)
