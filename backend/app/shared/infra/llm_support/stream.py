"""Streaming completion helper built on top of LiteLLM."""

from __future__ import annotations

import asyncio
import time
from typing import AsyncGenerator

from app.schemas.llm import ChatMessage
from app.shared.infra.exceptions import LLMCallError, LLMTimeoutError
from app.shared.infra.llm_support.routing import LLMCallPurpose
from app.shared.infra.observability.trace import langsmith_trace

from .litellm_loader import load_litellm
from .common import (
    build_completion_context,
    build_completion_kwargs,
    extract_usage,
    get_semaphore,
    logger,
    merge_usage,
    request_timeout_s,
    trace_log_fields,
    track_call,
)
from .observability import (
    _end_langsmith_trace,
    _langsmith_trace_kwargs,
    _record_new_token_event,
    _resolved_trace_model,
)

litellm = load_litellm()


async def acompletion_stream(
    messages: list[ChatMessage],
    *,
    call_purpose: LLMCallPurpose | None = None,
    task_type: LLMCallPurpose | None = None,
    model: str | None = None,
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

    async with get_semaphore():
        try:
            call_kwargs = build_completion_kwargs(
                context=context,
                messages=messages,
                extra_kwargs=kwargs,
            )
            call_kwargs["stream"] = True
            call_model, provider, tracked_model = _resolved_trace_model(
                call_kwargs,
                context.model,
            )
            logger.info(
                "llm_stream_started",
                model=tracked_model,
                task_type=context.task_type.value,
                timeout_s=context.profile.timeout_s,
            )
            streamed_chunks: list[str] = []
            usage = (0, 0, 0)
            first_token_seen = False
            with langsmith_trace(
                name="LLM：流式生成",
                run_type="llm",
                **_langsmith_trace_kwargs(
                    task_type=context.task_type,
                    call_model=call_model,
                    provider=provider,
                    model_name=tracked_model,
                    mode="stream",
                    messages=messages,
                    call_kwargs=call_kwargs,
                ),
            ) as trace_run:
                response = await asyncio.wait_for(
                    litellm.acompletion(**call_kwargs),
                    timeout=request_timeout_s(context.profile.timeout_s),
                )
                usage = merge_usage(usage, extract_usage(response))
                async for chunk in response:
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
            logger.warning(
                "llm_stream_timeout",
                elapsed_s=round(time.monotonic() - start, 2),
                model=tracked_model,
                task_type=context.task_type.value,
                timeout_s=context.profile.timeout_s,
                **trace_log_fields(),
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
            logger.info(
                "llm_stream_cancelled",
                elapsed_s=round(time.monotonic() - start, 2),
                model=tracked_model,
                task_type=context.task_type.value,
                **trace_log_fields(),
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
            logger.error("llm_stream_failed", error=str(exc), **trace_log_fields())
            raise LLMCallError(reason=str(exc)) from exc
