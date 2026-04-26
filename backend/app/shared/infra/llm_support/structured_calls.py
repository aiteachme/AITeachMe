"""Structured completion helper built on top of LiteLLM."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Any
from typing import TypeVar

try:
    import instructor
except ModuleNotFoundError:  # pragma: no cover - optional dependency in local dev
    instructor = None

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
    trace_log_fields,
    track_call,
)
from .observability import _end_langsmith_trace, _langsmith_trace_kwargs
from .structured import (
    _build_structured_fallback_messages,
    _parse_structured_response_text,
    _serialize_structured_result,
)

T = TypeVar("T")
litellm = load_litellm()


async def acompletion_structured(
    response_model: type[T],
    messages: list[ChatMessage],
    *,
    call_purpose: LLMCallPurpose | None = None,
    task_type: LLMCallPurpose | None = None,
    model: str | None = None,
    extra_metadata: Mapping[str, Any] | None = None,
    **kwargs,
) -> T:
    """Async structured completion."""

    context = build_completion_context(
        task_type=task_type,
        call_purpose=call_purpose,
        model=model,
    )
    use_instructor = instructor is not None
    client = instructor.from_litellm(litellm.acompletion) if use_instructor else None
    last_error: Exception | None = None
    call_started_at = time.monotonic()
    tracked_model = context.model

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
            prepared = prepare_completion_attempt(
                context=context,
                messages=messages,
                extra_kwargs=kwargs,
                attempt=attempt,
            )
            tracked_model = prepared.tracked_model
            log_attempt_started(
                "llm_structured_started",
                attempt=prepared,
                context=context,
                extra={
                    "response_model": response_model.__name__,
                    "mode": "instructor" if use_instructor else "json_prompt",
                },
            )
            try:
                prompt_t = 0
                completion_t = 0
                total_t = 0
                assistant_text = ""
                trace_messages = messages
                if not use_instructor:
                    trace_messages = _build_structured_fallback_messages(response_model, messages)
                    prepared.call_kwargs["messages"] = trace_messages
                with langsmith_trace(
                    name="LLM：结构化生成",
                    run_type="llm",
                    **_langsmith_trace_kwargs(
                        task_type=context.task_type,
                        call_model=prepared.call_model,
                        provider=prepared.provider,
                        model_name=tracked_model,
                        mode="structured",
                        messages=trace_messages,
                        call_kwargs=prepared.call_kwargs,
                        attempt=prepared.attempt,
                        extra_metadata=extra_metadata,
                    ),
                ) as trace_run:
                    if use_instructor:
                        assert client is not None
                        try:
                            result = await asyncio.wait_for(
                                client.chat.completions.create(
                                    response_model=response_model,
                                    max_retries=0,
                                    **prepared.call_kwargs,
                                ),
                                timeout=request_timeout_s(context.profile.timeout_s),
                            )
                            prompt_t, completion_t, total_t = extract_usage(result)
                        except asyncio.TimeoutError:
                            raise
                        except asyncio.CancelledError:
                            raise
                        except Exception as instructor_exc:
                            logger.warning(
                                "llm_structured_instructor_parse_failed_trying_repair",
                                response_model=response_model.__name__,
                                error=str(instructor_exc)[:200],
                                **trace_log_fields(),
                            )
                            raw_response = await asyncio.wait_for(
                                litellm.acompletion(**prepared.call_kwargs),
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
                            litellm.acompletion(**prepared.call_kwargs),
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
                    attempt=prepared.attempt,
                    elapsed_s=round(time.monotonic() - prepared.started_at, 2),
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
                log_attempt_timeout(
                    "llm_structured_timeout",
                    attempt=prepared,
                    context=context,
                    extra={
                        "response_model": response_model.__name__,
                        "mode": "instructor" if use_instructor else "json_prompt",
                    },
                )
            except asyncio.CancelledError:
                last_error = asyncio.CancelledError()
                log_attempt_cancelled(
                    "llm_structured_cancelled",
                    attempt=prepared,
                    context=context,
                    extra={
                        "response_model": response_model.__name__,
                        "mode": "instructor" if use_instructor else "json_prompt",
                    },
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
                    "llm_structured_failed",
                    attempt=prepared,
                    context=context,
                    error=exc,
                    extra={
                        "response_model": response_model.__name__,
                        "mode": "instructor" if use_instructor else "json_prompt",
                    },
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
