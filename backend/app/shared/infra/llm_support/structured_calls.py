"""Structured completion helper built on top of LiteLLM."""

from __future__ import annotations

import asyncio
import time
from typing import TypeVar

import litellm

try:
    import instructor
except ModuleNotFoundError:  # pragma: no cover - optional dependency in local dev
    instructor = None

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
from .observability import _end_langsmith_trace, _langsmith_trace_kwargs, _resolved_trace_model
from .structured import (
    _build_structured_fallback_messages,
    _parse_structured_response_text,
    _serialize_structured_result,
)

T = TypeVar("T")


async def acompletion_structured(
    response_model: type[T],
    messages: list[ChatMessage],
    *,
    task_type: TaskType = TaskType.DEFAULT,
    **kwargs,
) -> T:
    """Async structured completion."""

    context = build_completion_context(task_type)
    use_instructor = instructor is not None
    client = instructor.from_litellm(litellm.acompletion) if use_instructor else None
    last_error: Exception | None = None
    call_started_at = time.monotonic()
    tracked_model = context.profile.model

    if not use_instructor:
        logger.warning(
            "llm_structured_instructor_unavailable",
            response_model=response_model.__name__,
            model=tracked_model,
            task_type=context.task_type.value,
            fallback_mode="json_prompt",
            **trace_log_fields(),
        )

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
                context.profile.model,
            )
            logger.info(
                "llm_structured_started",
                attempt=attempt,
                response_model=response_model.__name__,
                model=tracked_model,
                task_type=context.task_type.value,
                timeout_s=context.profile.timeout_s,
                mode="instructor" if use_instructor else "json_prompt",
            )
            try:
                prompt_t = 0
                completion_t = 0
                total_t = 0
                assistant_text = ""
                trace_messages = messages
                if not use_instructor:
                    trace_messages = _build_structured_fallback_messages(response_model, messages)
                    call_kwargs["messages"] = trace_messages
                with langsmith_trace(
                    name="llm.acompletion_structured",
                    run_type="llm",
                    **_langsmith_trace_kwargs(
                        task_type=context.task_type,
                        call_model=call_model,
                        provider=provider,
                        model_name=tracked_model,
                        mode="structured",
                        messages=trace_messages,
                        call_kwargs=call_kwargs,
                        attempt=attempt,
                    ),
                ) as trace_run:
                    if use_instructor:
                        assert client is not None
                        try:
                            result = await asyncio.wait_for(
                                client.chat.completions.create(
                                    response_model=response_model,
                                    max_retries=0,
                                    **call_kwargs,
                                ),
                                timeout=request_timeout_s(context.profile.timeout_s),
                            )
                            prompt_t, completion_t, total_t = extract_usage(result)
                        except Exception as instructor_exc:
                            logger.warning(
                                "llm_structured_instructor_parse_failed_trying_repair",
                                response_model=response_model.__name__,
                                error=str(instructor_exc)[:200],
                                **trace_log_fields(),
                            )
                            raw_response = await asyncio.wait_for(
                                litellm.acompletion(**call_kwargs),
                                timeout=request_timeout_s(context.profile.timeout_s),
                            )
                            prompt_t, completion_t, total_t = extract_usage(raw_response)
                            raw_text = ""
                            tool_calls = getattr(raw_response.choices[0].message, "tool_calls", None)
                            if tool_calls:
                                raw_text = tool_calls[0].function.arguments or ""
                            if not raw_text:
                                raw_text = raw_response.choices[0].message.content or ""
                            assistant_text = raw_text
                            result = _parse_structured_response_text(response_model, raw_text)
                    else:
                        response = await asyncio.wait_for(
                            litellm.acompletion(**call_kwargs),
                            timeout=request_timeout_s(context.profile.timeout_s),
                        )
                        prompt_t, completion_t, total_t = extract_usage(response)
                        raw_content = response.choices[0].message.content or ""
                        assistant_text = raw_content
                        result = _parse_structured_response_text(response_model, raw_content)
                    _end_langsmith_trace(
                        trace_run,
                        text=assistant_text.strip() or _serialize_structured_result(result),
                        result=result,
                        prompt_tokens=prompt_t,
                        completion_tokens=completion_t,
                        total_tokens=total_t,
                    )
                logger.info(
                    "llm_structured_complete",
                    attempt=attempt,
                    elapsed_s=round(time.monotonic() - start, 2),
                    response_model=response_model.__name__,
                    model=tracked_model,
                    task_type=context.task_type.value,
                    mode="instructor" if use_instructor else "json_prompt",
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
                return result
            except asyncio.TimeoutError:
                last_error = LLMTimeoutError(timeout_s=context.profile.timeout_s)
                logger.warning(
                    "llm_structured_timeout",
                    attempt=attempt,
                    elapsed_s=round(time.monotonic() - start, 2),
                    response_model=response_model.__name__,
                    model=tracked_model,
                    task_type=context.task_type.value,
                    timeout_s=context.profile.timeout_s,
                    mode="instructor" if use_instructor else "json_prompt",
                    **trace_log_fields(),
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "llm_structured_failed",
                    attempt=attempt,
                    elapsed_s=round(time.monotonic() - start, 2),
                    response_model=response_model.__name__,
                    model=tracked_model,
                    task_type=context.task_type.value,
                    error=str(exc),
                    mode="instructor" if use_instructor else "json_prompt",
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
