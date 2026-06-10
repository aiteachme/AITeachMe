"""Streaming completion helper built on top of LiteLLM."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Any, AsyncGenerator

from app.schemas.llm import ChatMessage
from app.shared.infra.exceptions import LLMCallError, LLMTimeoutError
from app.shared.infra.observability.trace import langsmith_trace

from .common import (
    build_completion_contexts,
    effective_call_timeout_s,
    extract_usage,
    get_llm_concurrency_limiter,
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
from .litellm_loader import load_litellm
from .observability import (
    _end_langsmith_trace,
    _langsmith_trace_kwargs,
    _record_new_token_event,
)
from .responses_adapter import (
    chat_fallback_for_auto_responses,
    resolve_provider_call,
    response_stream_delta,
    response_stream_final_text,
)


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
    task_type: object | None = None,
    model: str | None = None,
    extra_metadata: Mapping[str, Any] | None = None,
    **kwargs,
) -> AsyncGenerator[str, None]:
    """Async streaming completion."""

    litellm = load_litellm()
    contexts = build_completion_contexts(
        task_type=task_type,
        model=model,
    )
    primary_context = contexts[0]
    start = time.monotonic()
    tracked_model = primary_context.model
    last_error: Exception | None = None

    async with get_llm_concurrency_limiter():
        for attempt_number, context in enumerate(contexts, start=1):
            prepared = prepare_completion_attempt(
                context=context,
                messages=messages,
                extra_kwargs=kwargs,
                attempt=attempt_number,
                override_kwargs={"stream": True},
            )
            tracked_model = prepared.tracked_model
            attempt_streamed_content = False
            try:
                log_attempt_started(
                    "llm_stream_started",
                    attempt=prepared,
                    context=context,
                )
                provider_call = resolve_provider_call(
                    context=context,
                    call_kwargs=prepared.call_kwargs,
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
                        mode=f"stream_{provider_call.api_mode}",
                        messages=messages,
                        call_kwargs=provider_call.kwargs,
                        endpoint_role=context.endpoint_role,
                        model_selector=context.model_selector,
                        extra_metadata=extra_metadata,
                    ),
                ) as trace_run:
                    try:
                        provider_coro = (
                            litellm.aresponses(**provider_call.kwargs)
                            if provider_call.api_mode == "responses"
                            else litellm.acompletion(**provider_call.kwargs)
                        )
                        response = await asyncio.wait_for(
                            provider_coro,
                            timeout=context_request_timeout_s(context, provider_call.kwargs),
                        )
                    except Exception as provider_exc:
                        fallback_call = chat_fallback_for_auto_responses(
                            provider_call,
                            provider_exc,
                        )
                        if fallback_call is None:
                            raise
                        logger.warning(
                            "llm_stream_auto_responses_fallback_to_chat",
                            attempt=prepared.attempt,
                            model=tracked_model,
                            task_type=context.task_type,
                            endpoint_role=context.endpoint_role,
                            error=str(provider_exc),
                        )
                        provider_call = fallback_call
                        response = await asyncio.wait_for(
                            litellm.acompletion(**provider_call.kwargs),
                            timeout=context_request_timeout_s(context, provider_call.kwargs),
                        )
                    usage = merge_usage(usage, extract_usage(response))
                    try:
                        async for chunk in _stream_chunks_with_timeout(
                            response,
                            timeout_s=context_request_timeout_s(context, provider_call.kwargs),
                        ):
                            usage = merge_usage(usage, extract_usage(chunk))
                            if provider_call.api_mode == "responses":
                                content = response_stream_delta(chunk)
                                if not content and not streamed_chunks:
                                    content = response_stream_final_text(chunk)
                            else:
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
                            attempt_streamed_content = True
                            yield content
                    except Exception as exc:
                        if not streamed_chunks or not _is_stream_usage_calculation_error(exc):
                            raise
                        logger.info(
                            "llm_stream_usage_calculation_failed_ignored",
                            model=tracked_model,
                            task_type=context.task_type,
                            endpoint_role=context.endpoint_role,
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
                    task_type=context.task_type,
                    endpoint_role=context.endpoint_role,
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
                return
            except asyncio.TimeoutError:
                last_error = LLMTimeoutError(
                    timeout_s=effective_call_timeout_s(context, prepared.call_kwargs)
                )
                log_attempt_timeout(
                    "llm_stream_timeout",
                    attempt=prepared,
                    context=context,
                )
                if attempt_streamed_content:
                    track_call(
                        task_type=context.task_type,
                        model=tracked_model,
                        start=start,
                        success=False,
                        error="timeout_after_stream_started",
                    )
                    raise last_error
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
                last_error = exc
                log_attempt_failed(
                    "llm_stream_failed",
                    attempt=prepared,
                    context=context,
                    error=exc,
                    level="error" if attempt_streamed_content else "warning",
                )
                if attempt_streamed_content:
                    track_call(
                        task_type=context.task_type,
                        model=tracked_model,
                        start=start,
                        success=False,
                        error=str(exc),
                    )
                    raise LLMCallError(reason=str(exc)) from exc

        track_call(
            task_type=primary_context.task_type,
            model=tracked_model,
            start=start,
            success=False,
            error=str(last_error),
        )
        if isinstance(last_error, LLMTimeoutError):
            raise last_error
        raise LLMCallError(reason=str(last_error or "unknown_error")) from last_error
