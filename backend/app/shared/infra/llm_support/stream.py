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
    completion_context_groups,
    effective_call_timeout_s,
    effective_endpoint_group_max_retries,
    extract_usage,
    get_llm_concurrency_limiter,
    logger,
    iter_with_overall_timeout,
    log_attempt_cancelled,
    log_attempt_failed,
    log_attempt_started,
    log_attempt_timeout,
    merge_usage,
    prepare_completion_attempt,
    pop_overall_timeout_s,
    context_request_timeout_s,
    should_try_endpoint_fallback,
    sleep_before_retry,
    track_call,
)
from .litellm_loader import load_litellm
from .observability import (
    _end_langsmith_trace,
    _langsmith_trace_kwargs,
    _record_new_token_event,
    llm_api_mode_outputs,
)
from .responses_adapter import (
    ProviderCall,
    chat_fallback_for_auto_responses,
    extract_response_text,
    provider_call_metadata,
    resolve_provider_call,
    response_output_tool_events,
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


def _stream_chunk_content(
    *,
    provider_call: ProviderCall,
    chunk: Any,
    streamed_chunks: list[str],
) -> str | None:
    if provider_call.api_mode == "responses":
        content = response_stream_delta(chunk)
        if not content and not streamed_chunks:
            content = response_stream_final_text(chunk)
        return content

    choices = getattr(chunk, "choices", None) or []
    if not choices:
        return None
    delta = getattr(choices[0], "delta", None)
    return getattr(delta, "content", None) if delta is not None else None


async def _stream_content_parts(
    *,
    response: Any,
    context,
    provider_call: ProviderCall,
    trace_run: Any,
    usage: tuple[int, int, int],
    streamed_chunks: list[str],
    provider_tool_events: list[dict[str, str]],
) -> AsyncGenerator[tuple[str, tuple[int, int, int]], None]:
    first_token_seen = bool(streamed_chunks)
    if not hasattr(response, "__aiter__"):
        content = _non_stream_response_text(provider_call=provider_call, response=response)
        if content:
            if not first_token_seen:
                _record_new_token_event(trace_run)
            streamed_chunks.append(content)
            yield content, usage
        return

    async for chunk in _stream_chunks_with_timeout(
        response,
        timeout_s=context_request_timeout_s(context, provider_call.kwargs),
    ):
        usage = merge_usage(usage, extract_usage(chunk))
        if provider_call.api_mode == "responses":
            for event in response_output_tool_events(_get_response_payload(chunk)):
                if event not in provider_tool_events:
                    provider_tool_events.append(event)
        content = _stream_chunk_content(
            provider_call=provider_call,
            chunk=chunk,
            streamed_chunks=streamed_chunks,
        )
        if not content:
            continue
        if not first_token_seen:
            _record_new_token_event(trace_run)
            first_token_seen = True
        streamed_chunks.append(content)
        yield content, usage


def _get_response_payload(chunk: Any) -> Any:
    if isinstance(chunk, Mapping):
        return chunk.get("response") or chunk
    return getattr(chunk, "response", None) or chunk


def _non_stream_response_text(
    *,
    provider_call: ProviderCall,
    response: Any,
) -> str:
    if provider_call.api_mode == "responses":
        return extract_response_text(response)

    choices = getattr(response, "choices", None) or []
    for choice in choices:
        message = getattr(choice, "message", None)
        content = getattr(message, "content", None) if message is not None else None
        if content:
            return str(content)
        text = getattr(choice, "text", None)
        if text:
            return str(text)
    return response if isinstance(response, str) else ""


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

    overall_timeout_s = pop_overall_timeout_s(kwargs)
    stream = iter_with_overall_timeout(
        _acompletion_stream_impl(
            messages,
            task_type=task_type,
            model=model,
            extra_metadata=extra_metadata,
            kwargs=kwargs,
        ),
        overall_timeout_s,
    )
    try:
        async for chunk in stream:
            yield chunk
    finally:
        await stream.aclose()


async def _acompletion_stream_impl(
    messages: list[ChatMessage],
    *,
    task_type: object | None,
    model: str | None,
    extra_metadata: Mapping[str, Any] | None,
    kwargs: dict[str, Any],
) -> AsyncGenerator[str, None]:
    litellm = load_litellm()
    contexts = build_completion_contexts(
        task_type=task_type,
        model=model,
    )
    primary_context = contexts[0]
    start = time.monotonic()
    tracked_model = primary_context.model
    last_error: Exception | None = None

    attempt_number = 0
    async with get_llm_concurrency_limiter():
        for group_index, context_group in enumerate(completion_context_groups(contexts)):
            if (
                group_index > 0
                and context_group[0].endpoint_role == "fallback"
                and not should_try_endpoint_fallback(last_error)
            ):
                logger.warning(
                    "llm_stream_endpoint_fallback_skipped_non_endpoint_error",
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
                        initial_api_mode = provider_call.api_mode
                        route_reason = provider_call.route_reason
                        auto_responses_chat_fallback = False
                        trace_metadata = {
                            **dict(extra_metadata or {}),
                            **provider_call_metadata(provider_call),
                        }
                        streamed_chunks: list[str] = []
                        provider_tool_events: list[dict[str, str]] = []
                        usage = (0, 0, 0)
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
                                extra_metadata=trace_metadata,
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
                                auto_responses_chat_fallback = True
                                logger.warning(
                                    "llm_stream_auto_responses_fallback_to_chat",
                                    attempt=prepared.attempt,
                                    model=tracked_model,
                                    task_type=context.task_type,
                                    endpoint_role=context.endpoint_role,
                                    route_reason=route_reason,
                                    error=str(provider_exc),
                                )
                                provider_call = fallback_call
                                response = await asyncio.wait_for(
                                    litellm.acompletion(**provider_call.kwargs),
                                    timeout=context_request_timeout_s(context, provider_call.kwargs),
                                )
                            usage = merge_usage(usage, extract_usage(response))
                            try:
                                async for content, usage in _stream_content_parts(
                                    response=response,
                                    context=context,
                                    provider_call=provider_call,
                                    trace_run=trace_run,
                                    usage=usage,
                                    streamed_chunks=streamed_chunks,
                                    provider_tool_events=provider_tool_events,
                                ):
                                    attempt_streamed_content = True
                                    yield content
                            except Exception as exc:
                                fallback_call = chat_fallback_for_auto_responses(
                                    provider_call,
                                    exc,
                                )
                                fallback_stream_succeeded = False
                                if fallback_call is not None and not streamed_chunks:
                                    auto_responses_chat_fallback = True
                                    logger.warning(
                                        "llm_stream_auto_responses_iteration_fallback_to_chat",
                                        attempt=prepared.attempt,
                                        model=tracked_model,
                                        task_type=context.task_type,
                                        endpoint_role=context.endpoint_role,
                                        route_reason=route_reason,
                                        error=str(exc),
                                    )
                                    provider_call = fallback_call
                                    response = await asyncio.wait_for(
                                        litellm.acompletion(**provider_call.kwargs),
                                        timeout=context_request_timeout_s(context, provider_call.kwargs),
                                    )
                                    usage = merge_usage(usage, extract_usage(response))
                                    async for content, usage in _stream_content_parts(
                                        response=response,
                                        context=context,
                                        provider_call=provider_call,
                                        trace_run=trace_run,
                                        usage=usage,
                                        streamed_chunks=streamed_chunks,
                                        provider_tool_events=provider_tool_events,
                                    ):
                                        attempt_streamed_content = True
                                        yield content
                                    fallback_stream_succeeded = True
                                if not fallback_stream_succeeded:
                                    if not streamed_chunks or not _is_stream_usage_calculation_error(exc):
                                        raise
                                    logger.info(
                                        "llm_stream_usage_calculation_failed_ignored",
                                        model=tracked_model,
                                        task_type=context.task_type,
                                        endpoint_role=context.endpoint_role,
                                        error=str(exc),
                                    )
                            if not "".join(streamed_chunks).strip():
                                raise ValueError("empty_llm_response")
                            prompt_t, completion_t, total_t = usage
                            extra_outputs = llm_api_mode_outputs(
                                initial_api_mode=initial_api_mode,
                                final_api_mode=provider_call.api_mode,
                                final_route_reason=provider_call.route_reason,
                                auto_responses_chat_fallback=auto_responses_chat_fallback,
                            )
                            if provider_tool_events:
                                extra_outputs["llm_provider_tool_events"] = provider_tool_events
                            _end_langsmith_trace(
                                trace_run,
                                text="".join(streamed_chunks),
                                extra_outputs=extra_outputs,
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
                            initial_api_mode=initial_api_mode,
                            final_api_mode=provider_call.api_mode,
                            initial_route_reason=route_reason,
                            final_route_reason=provider_call.route_reason,
                            auto_responses_chat_fallback=auto_responses_chat_fallback,
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

                if retry_round < group_max_retries:
                    await sleep_before_retry(retry_round, error=last_error)

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
