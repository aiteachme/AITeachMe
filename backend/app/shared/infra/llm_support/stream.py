"""Streaming completion helper built on top of LiteLLM."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Any, AsyncGenerator

from app.schemas.llm import ChatMessage
from app.shared.infra.exceptions import LLMCallError, LLMTimeoutError
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
    merge_usage,
    prepare_completion_attempt,
    context_request_timeout_s,
    track_call,
)
from .observability import (
    _end_langsmith_trace,
    _langsmith_trace_kwargs,
    _record_new_token_event,
)

litellm = load_litellm()


def _is_stream_usage_calculation_error(exc: Exception) -> bool:
    """Return whether LiteLLM failed only while calculating final stream usage."""

    message = str(exc).lower()
    return (
        "error building chunks for logging/streaming usage calculation" in message
        or "streaming usage calculation" in message
    )


async def _stream_chunks_with_timeout(
    response: Any,
    *,
    timeout_s: int | None,
) -> AsyncGenerator[Any, None]:
    """Yield streaming chunks while enforcing a timeout for each upstream read."""

    iterator = response.__aiter__()
    try:
        while True:
            try:
                yield await asyncio.wait_for(iterator.__anext__(), timeout=timeout_s)
            except StopAsyncIteration:
                break
    finally:
        close = getattr(iterator, "aclose", None) or getattr(response, "aclose", None)
        if callable(close):
            try:
                await close()
            except Exception:
                pass


async def acompletion_stream(
    messages: list[ChatMessage],
    *,
    call_purpose: LLMCallPurpose | None = None,
    task_type: LLMCallPurpose | None = None,
    model: str | None = None,
    extra_metadata: Mapping[str, Any] | None = None,
    **kwargs,
) -> AsyncGenerator[str, None]:
    """Async streaming completion."""

    context = build_completion_context(
        task_type=task_type,
        call_purpose=call_purpose,
        model=model,
    )
    start = time.monotonic()
    tracked_model = context.model
    prepared = prepare_completion_attempt(
        context=context,
        messages=messages,
        extra_kwargs=kwargs,
        attempt=1,
        override_kwargs={"stream": True},
    )

    async with get_semaphore():
        try:
            tracked_model = prepared.tracked_model
            log_attempt_started(
                "llm_stream_started",
                attempt=prepared,
                context=context,
            )
            streamed_chunks: list[str] = []
            usage = (0, 0, 0)
            first_token_seen = False
            with langsmith_trace(
                name="LLM：流式生成",
                run_type="llm",
                **_langsmith_trace_kwargs(
                    task_type=context.task_type,
                    call_model=prepared.call_model,
                    provider=prepared.provider,
                    model_name=tracked_model,
                    mode="stream",
                    messages=messages,
                    call_kwargs=prepared.call_kwargs,
                    extra_metadata=extra_metadata,
                ),
            ) as trace_run:
                response = await asyncio.wait_for(
                    litellm.acompletion(**prepared.call_kwargs),
                    timeout=context_request_timeout_s(context),
                )
                usage = merge_usage(usage, extract_usage(response))
                try:
                    async for chunk in _stream_chunks_with_timeout(
                        response,
                        timeout_s=context_request_timeout_s(context),
                    ):
                        usage = merge_usage(usage, extract_usage(chunk))
                        choices = getattr(chunk, "choices", None) or []
                        if not choices:
                            continue
                        delta = getattr(choices[0], "delta", None)
                        content = getattr(delta, "content", None) if delta is not None else None
                        if not content:
                            continue
                        if not first_token_seen:
                            _record_new_token_event(trace_run)
                            first_token_seen = True
                        streamed_chunks.append(content)
                        yield content
                except Exception as exc:
                    if not streamed_chunks or not _is_stream_usage_calculation_error(exc):
                        raise
                    logger.info(
                        "llm_stream_usage_calculation_failed_ignored",
                        model=tracked_model,
                        task_type=context.task_type.value,
                        error=str(exc),
                    )
                prompt_t, completion_t, total_t = usage
                _end_langsmith_trace(
                    trace_run,
                    text="".join(streamed_chunks),
                    prompt_tokens=prompt_t,
                    completion_tokens=completion_t,
                    total_tokens=total_t,
                )
            logger.info(
                "llm_stream_complete",
                elapsed_s=round(time.monotonic() - start, 2),
                model=tracked_model,
                task_type=context.task_type.value,
            )
            prompt_t, completion_t, total_t = usage
            track_call(
                task_type=context.task_type,
                model=tracked_model,
                start=start,
                success=True,
                prompt_tokens=prompt_t,
                completion_tokens=completion_t,
                total_tokens=total_t,
            )
        except asyncio.TimeoutError:
            log_attempt_timeout(
                "llm_stream_timeout",
                attempt=prepared,
                context=context,
            )
            track_call(
                task_type=context.task_type,
                model=tracked_model,
                start=start,
                success=False,
                error="timeout",
            )
            raise LLMTimeoutError(timeout_s=context.profile.timeout_s)
        except asyncio.CancelledError:
            log_attempt_cancelled(
                "llm_stream_cancelled",
                attempt=prepared,
                context=context,
            )
            track_call(
                task_type=context.task_type,
                model=tracked_model,
                start=start,
                success=False,
                error="cancelled",
            )
            raise
        except Exception as exc:
            track_call(
                task_type=context.task_type,
                model=tracked_model,
                start=start,
                success=False,
                error=str(exc),
            )
            log_attempt_failed(
                "llm_stream_failed",
                attempt=prepared,
                context=context,
                error=exc,
                level="error",
            )
            raise LLMCallError(reason=str(exc)) from exc
