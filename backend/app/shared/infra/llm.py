"""统一的 LLM 调用封装。

支持：
- 按任务类型选择模型（model_router）
- 调用追踪与统计（tracing）
- 文本补全 / 结构化补全 / 流式补全
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, AsyncGenerator, TypeVar

import litellm
from pydantic import BaseModel
import structlog
try:
    import instructor
except ModuleNotFoundError:  # pragma: no cover - optional dependency in local dev
    instructor = None

from app.shared.infra.tracing import (
    LLMCallRecord,
    get_llm_trace_context,
    get_tracker,
    langsmith_trace,
)
from app.shared.infra.config import get_settings
from app.shared.infra.exceptions import LLMCallError, LLMTimeoutError
from app.shared.infra.model_router import TaskType, get_task_profile
from app.schemas.llm import ChatMessage

logger = structlog.get_logger()

T = TypeVar("T")

# 保留原始常量作为兜底
_MAX_RETRIES = 3
_TIMEOUT_S = 60
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)

# 全局并发限制：防止 workflows 用 asyncio.gather 同时发太多 LLM 请求
# 通过环境变量 LLM_CONCURRENCY_LIMIT 调整，默认 10
_LLM_SEMAPHORE: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _LLM_SEMAPHORE
    if _LLM_SEMAPHORE is None:
        _LLM_SEMAPHORE = asyncio.Semaphore(get_settings().llm_concurrency_limit)
    return _LLM_SEMAPHORE


def _extract_usage(response) -> tuple[int, int, int]:
    """从 LiteLLM response 中提取 token 用量。"""

    try:
        usage = response.usage
        return (
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0,
            getattr(usage, "total_tokens", 0) or 0,
        )
    except Exception:
        return 0, 0, 0


def _trace_log_fields() -> dict[str, str]:
    trace = get_llm_trace_context()
    fields: dict[str, str] = {}
    if trace.subject:
        fields["subject"] = trace.subject
    if trace.build_session_id:
        fields["build_session_id"] = trace.build_session_id
    if trace.workflow:
        fields["workflow"] = trace.workflow
    if trace.lane:
        fields["lane"] = trace.lane
    if trace.node:
        fields["node"] = trace.node
    return fields


def _build_completion_kwargs(
    *,
    profile,
    settings,
    api_key: str,
    messages: list[ChatMessage],
    extra_kwargs: dict,
) -> dict:
    completion_kwargs = {
        "model": f"openai/{profile.model}",
        "messages": messages,
        "api_base": settings.llm_base_url,
        "api_key": api_key,
        "timeout": profile.timeout_s,
        "temperature": extra_kwargs.pop("temperature", profile.temperature),
    }
    if profile.max_tokens is not None:
        completion_kwargs["max_tokens"] = profile.max_tokens
    completion_kwargs.update(extra_kwargs)
    return completion_kwargs


def _langsmith_usage(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
) -> dict[str, int]:
    return {
        "input_tokens": int(prompt_tokens),
        "output_tokens": int(completion_tokens),
        "total_tokens": int(total_tokens),
    }


def _serialize_langsmith_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _langsmith_tool_calls(message: Any) -> list[dict[str, Any]]:
    tool_calls = getattr(message, "tool_calls", None) or []
    return [
        {
            "id": tool_call.id,
            "type": tool_call.type or "function",
            "function": {
                "name": tool_call.function.name,
                "arguments": tool_call.function.arguments,
            },
        }
        for tool_call in tool_calls
    ]


def _langsmith_outputs(
    *,
    text: str | None = None,
    result: Any = None,
    tool_calls: list[dict[str, Any]] | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
) -> dict[str, Any]:
    outputs: dict[str, Any] = {
        "usage": _langsmith_usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
    }
    if text is not None:
        outputs["text"] = text
    if result is not None:
        outputs["result"] = _serialize_langsmith_value(result)
    if tool_calls:
        outputs["tool_calls"] = tool_calls
    return outputs


def _end_langsmith_trace(
    trace_run: Any | None,
    *,
    text: str | None = None,
    result: Any = None,
    tool_calls: list[dict[str, Any]] | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
) -> None:
    if trace_run is None:
        return
    trace_run.end(
        outputs=_langsmith_outputs(
            text=text,
            result=result,
            tool_calls=tool_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
    )


def _serialize_structured_result(result: Any) -> str:
    if isinstance(result, BaseModel):
        return result.model_dump_json()
    return json.dumps(result, ensure_ascii=False, default=str)


def _langsmith_llm_metadata(
    *,
    task_type: TaskType,
    model: str,
    attempt: int | None = None,
    mode: str,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "task_type": task_type.value,
        "model": model,
        "mode": mode,
    }
    if attempt is not None:
        metadata["attempt"] = attempt
    return metadata


def _langsmith_trace_kwargs(
    *,
    task_type: TaskType,
    model: str,
    mode: str,
    messages: list[ChatMessage],
    attempt: int | None = None,
    tools: list[dict] | None = None,
) -> dict[str, Any]:
    trace_context = get_llm_trace_context()
    inputs: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    if tools:
        inputs["tools"] = tools
    return {
        "inputs": inputs,
        "subject": trace_context.subject,
        "build_session_id": trace_context.build_session_id,
        "workflow": trace_context.workflow,
        "lane": trace_context.lane,
        "node": trace_context.node,
        "extra_metadata": _langsmith_llm_metadata(
            task_type=task_type,
            model=model,
            attempt=attempt,
            mode=mode,
        ),
        "extra_tags": [
            f"task:{task_type.value}",
            f"mode:{mode}",
        ],
    }


def _model_json_schema(response_model: type[T]) -> dict[str, Any]:
    schema_builder = getattr(response_model, "model_json_schema", None)
    if callable(schema_builder):
        return schema_builder()
    legacy_builder = getattr(response_model, "schema", None)
    if callable(legacy_builder):
        return legacy_builder()
    return {}


def _build_structured_fallback_messages(
    response_model: type[T],
    messages: list[ChatMessage],
) -> list[ChatMessage]:
    schema = json.dumps(
        _model_json_schema(response_model),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    fallback_instruction = (
        "Return only valid JSON that can be parsed directly. "
        "Do not include markdown code fences, commentary, or extra text. "
        f"The JSON must satisfy this schema: {schema}"
    )
    return [
        *messages,
        {"role": "user", "content": fallback_instruction},
    ]


def _structured_model_validate(response_model: type[T], payload: Any) -> T:
    validator = getattr(response_model, "model_validate", None)
    if callable(validator):
        return validator(payload)
    legacy_validator = getattr(response_model, "parse_obj", None)
    if callable(legacy_validator):
        return legacy_validator(payload)
    return response_model(**payload)


def _repair_truncated_json(raw: str) -> str | None:
    """Try to fix truncated JSON by appending missing closing brackets/braces.

    Handles the common case where LLM tool_call arguments are cut off mid-string,
    e.g. ``{"title": "foo", "items": ["a", "b"`` → ``{"title": "foo", "items": ["a", "b"]}``.
    """
    stripped = raw.rstrip()
    if not stripped:
        return None
    # Find latest unmatched openers
    stack: list[str] = []
    in_string = False
    escape_next = False
    for char in stripped:
        if escape_next:
            escape_next = False
            continue
        if char == "\\":
            escape_next = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char in ("{", "["):
            stack.append("}" if char == "{" else "]")
        elif char in ("}", "]"):
            if stack and stack[-1] == char:
                stack.pop()
    if not stack:
        return None  # Already balanced – nothing to repair
    # If we're in the middle of a string, close it first
    if in_string:
        stripped += '"'
    # Append missing closers in reverse order
    stripped += "".join(reversed(stack))
    return stripped


def _extract_json_candidates(raw_text: str) -> list[str]:
    stripped = (raw_text or "").strip()
    candidates: list[str] = []
    if stripped:
        candidates.append(stripped)

    for match in _JSON_FENCE_RE.finditer(raw_text or ""):
        fenced = match.group(1).strip()
        if fenced:
            candidates.append(fenced)

    for opener, closer in (("{", "}"), ("[", "]")):
        start = stripped.find(opener)
        end = stripped.rfind(closer)
        if start != -1 and end != -1 and end >= start:
            candidates.append(stripped[start : end + 1])

    # Try to repair truncated JSON as a last resort
    repaired = _repair_truncated_json(stripped)
    if repaired and repaired != stripped:
        candidates.append(repaired)

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = candidate.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _parse_structured_response_text(response_model: type[T], raw_text: str) -> T:
    candidates = _extract_json_candidates(raw_text)
    errors: list[str] = []
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as exc:
            errors.append(f"json_decode_error:{exc.msg}")
            continue
        try:
            return _structured_model_validate(response_model, payload)
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(f"model_validate_error:{exc}")

    reason = errors[0] if errors else "empty_or_non_json_response"
    raise LLMCallError(reason=f"structured_parse_failed: {reason}")

def _track_call(
    *,
    task_type: str,
    model: str,
    start: float,
    success: bool,
    error: str | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
) -> None:
    """记录一次 LLM 调用（如果启用了观测）。"""

    settings = get_settings()
    if not settings.llm_observability_enabled:
        return

    trace_context = get_llm_trace_context()
    record = LLMCallRecord(
        task_type=task_type,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        latency_s=round(time.monotonic() - start, 3),
        success=success,
        error=error,
        subject=trace_context.subject,
        build_session_id=trace_context.build_session_id,
        workflow=trace_context.workflow,
        lane=trace_context.lane,
        node=trace_context.node,
    )
    get_tracker().record(record)


async def acompletion(
    messages: list[ChatMessage],
    *,
    task_type: TaskType = TaskType.DEFAULT,
    **kwargs,
) -> str:
    """异步文本补全。

    Args:
        messages: 消息列表。
        task_type: 任务类型，用于模型路由（默认 DEFAULT，向后兼容）。
        **kwargs: 透传给 LiteLLM 的其他参数。
    """

    settings = get_settings()
    api_key = settings.require_llm_api_key()
    profile = get_task_profile(task_type)
    last_error: Exception | None = None
    call_started_at = time.monotonic()

    async with _get_semaphore():
        for attempt in range(1, profile.max_retries + 1):
            start = time.monotonic()
            call_kwargs = _build_completion_kwargs(
                profile=profile,
                settings=settings,
                api_key=api_key,
                messages=messages,
                extra_kwargs=dict(kwargs),
            )
            logger.info(
                "llm_completion_started",
                attempt=attempt,
                model=profile.model,
                task_type=task_type.value,
                timeout_s=profile.timeout_s,
            )
            try:
                with langsmith_trace(
                    name="llm.acompletion",
                    run_type="llm",
                    **_langsmith_trace_kwargs(
                        task_type=task_type,
                        model=profile.model,
                        mode="text",
                        messages=messages,
                        attempt=attempt,
                    ),
                ) as trace_run:
                    response = await asyncio.wait_for(
                        litellm.acompletion(**call_kwargs),
                        timeout=profile.timeout_s + 2,
                    )
                    prompt_t, completion_t, total_t = _extract_usage(response)
                    _end_langsmith_trace(
                        trace_run,
                        text=response.choices[0].message.content or "",
                        prompt_tokens=prompt_t,
                        completion_tokens=completion_t,
                        total_tokens=total_t,
                    )
                logger.info(
                    "llm_completion_complete",
                    attempt=attempt,
                    elapsed_s=round(time.monotonic() - start, 2),
                    model=profile.model,
                    task_type=task_type.value,
                )
                _track_call(
                    task_type=task_type.value,
                    model=profile.model,
                    start=call_started_at,
                    success=True,
                    prompt_tokens=prompt_t,
                    completion_tokens=completion_t,
                    total_tokens=total_t,
                )
                return response.choices[0].message.content
            except asyncio.TimeoutError:
                last_error = LLMTimeoutError(timeout_s=profile.timeout_s)
                logger.warning(
                    "llm_completion_timeout",
                    attempt=attempt,
                    elapsed_s=round(time.monotonic() - start, 2),
                    model=profile.model,
                    task_type=task_type.value,
                    timeout_s=profile.timeout_s,
                    **_trace_log_fields(),
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "llm_completion_failed",
                    attempt=attempt,
                    elapsed_s=round(time.monotonic() - start, 2),
                    model=profile.model,
                    task_type=task_type.value,
                    error=str(exc),
                    **_trace_log_fields(),
                )

            if attempt < profile.max_retries:
                await asyncio.sleep(attempt * 2)

    _track_call(
        task_type=task_type.value,
        model=profile.model,
        start=call_started_at,
        success=False,
        error=str(last_error),
    )
    if isinstance(last_error, LLMTimeoutError):
        raise last_error
    raise LLMCallError(reason=str(last_error)) from last_error


async def acompletion_structured(
    response_model: type[T],
    messages: list[ChatMessage],
    *,
    task_type: TaskType = TaskType.DEFAULT,
    **kwargs,
) -> T:
    """异步结构化补全。

    Args:
        response_model: Pydantic 响应模型。
        messages: 消息列表。
        task_type: 任务类型，用于模型路由。
        **kwargs: 透传给 Instructor 或 LiteLLM 的额外参数。
    """

    settings = get_settings()
    api_key = settings.require_llm_api_key()
    profile = get_task_profile(task_type)
    use_instructor = instructor is not None
    client = instructor.from_litellm(litellm.acompletion) if use_instructor else None
    last_error: Exception | None = None
    call_started_at = time.monotonic()

    if not use_instructor:
        logger.warning(
            "llm_structured_instructor_unavailable",
            response_model=response_model.__name__,
            model=profile.model,
            task_type=task_type.value,
            fallback_mode="json_prompt",
            **_trace_log_fields(),
        )

    async with _get_semaphore():
        for attempt in range(1, profile.max_retries + 1):
            start = time.monotonic()
            call_kwargs = _build_completion_kwargs(
                profile=profile,
                settings=settings,
                api_key=api_key,
                messages=messages,
                extra_kwargs=dict(kwargs),
            )
            logger.info(
                "llm_structured_started",
                attempt=attempt,
                response_model=response_model.__name__,
                model=profile.model,
                task_type=task_type.value,
                timeout_s=profile.timeout_s,
                mode="instructor" if use_instructor else "json_prompt",
            )
            try:
                prompt_t = 0
                completion_t = 0
                total_t = 0
                assistant_text = ""
                with langsmith_trace(
                    name="llm.acompletion_structured",
                    run_type="llm",
                    **_langsmith_trace_kwargs(
                        task_type=task_type,
                        model=profile.model,
                        mode="structured",
                        messages=messages,
                        attempt=attempt,
                    ),
                ) as trace_run:
                    if use_instructor:
                        try:
                            result = await asyncio.wait_for(
                                client.chat.completions.create(
                                    response_model=response_model,
                                    max_retries=0,
                                    **call_kwargs,
                                ),
                                timeout=profile.timeout_s + 2,
                            )
                            prompt_t, completion_t, total_t = _extract_usage(result)
                        except Exception as instructor_exc:
                            logger.warning(
                                "llm_structured_instructor_parse_failed_trying_repair",
                                response_model=response_model.__name__,
                                error=str(instructor_exc)[:200],
                                **_trace_log_fields(),
                            )
                            raw_response = await asyncio.wait_for(
                                litellm.acompletion(**call_kwargs),
                                timeout=profile.timeout_s + 2,
                            )
                            prompt_t, completion_t, total_t = _extract_usage(raw_response)
                            raw_text = ""
                            tool_calls = getattr(raw_response.choices[0].message, "tool_calls", None)
                            if tool_calls:
                                raw_text = tool_calls[0].function.arguments or ""
                            if not raw_text:
                                raw_text = raw_response.choices[0].message.content or ""
                            assistant_text = raw_text
                            result = _parse_structured_response_text(response_model, raw_text)
                    else:
                        call_kwargs["messages"] = _build_structured_fallback_messages(
                            response_model,
                            call_kwargs["messages"],
                        )
                        response = await asyncio.wait_for(
                            litellm.acompletion(**call_kwargs),
                            timeout=profile.timeout_s + 2,
                        )
                        prompt_t, completion_t, total_t = _extract_usage(response)
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
                    model=profile.model,
                    task_type=task_type.value,
                    mode="instructor" if use_instructor else "json_prompt",
                )
                _track_call(
                    task_type=task_type.value,
                    model=profile.model,
                    start=call_started_at,
                    success=True,
                    prompt_tokens=prompt_t,
                    completion_tokens=completion_t,
                    total_tokens=total_t,
                )
                return result
            except asyncio.TimeoutError:
                last_error = LLMTimeoutError(timeout_s=profile.timeout_s)
                logger.warning(
                    "llm_structured_timeout",
                    attempt=attempt,
                    elapsed_s=round(time.monotonic() - start, 2),
                    response_model=response_model.__name__,
                    model=profile.model,
                    task_type=task_type.value,
                    timeout_s=profile.timeout_s,
                    mode="instructor" if use_instructor else "json_prompt",
                    **_trace_log_fields(),
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "llm_structured_failed",
                    attempt=attempt,
                    elapsed_s=round(time.monotonic() - start, 2),
                    response_model=response_model.__name__,
                    model=profile.model,
                    task_type=task_type.value,
                    error=str(exc),
                    mode="instructor" if use_instructor else "json_prompt",
                    **_trace_log_fields(),
                )

            if attempt < profile.max_retries:
                await asyncio.sleep(attempt * 2)

    _track_call(
        task_type=task_type.value,
        model=profile.model,
        start=call_started_at,
        success=False,
        error=str(last_error),
    )
    if isinstance(last_error, LLMTimeoutError):
        raise last_error
    raise LLMCallError(reason=str(last_error)) from last_error


async def acompletion_stream(
    messages: list[ChatMessage],
    *,
    task_type: TaskType = TaskType.DEFAULT,
    **kwargs,
) -> AsyncGenerator[str, None]:
    """异步流式补全。

    Args:
        messages: 消息列表。
        task_type: 任务类型，用于模型路由。
        **kwargs: 透传给 LiteLLM 的其他参数。
    """

    settings = get_settings()
    api_key = settings.require_llm_api_key()
    profile = get_task_profile(task_type)
    start = time.monotonic()

    async with _get_semaphore():
        try:
            call_kwargs = _build_completion_kwargs(
                profile=profile,
                settings=settings,
                api_key=api_key,
                messages=messages,
                extra_kwargs=dict(kwargs),
            )
            call_kwargs["stream"] = True
            logger.info(
                "llm_stream_started",
                model=profile.model,
                task_type=task_type.value,
                timeout_s=profile.timeout_s,
            )
            streamed_chunks: list[str] = []
            with langsmith_trace(
                name="llm.acompletion_stream",
                run_type="llm",
                **_langsmith_trace_kwargs(
                    task_type=task_type,
                    model=profile.model,
                    mode="stream",
                    messages=messages,
                ),
            ) as trace_run:
                response = await asyncio.wait_for(
                    litellm.acompletion(**call_kwargs),
                    timeout=profile.timeout_s + 2,
                )
                async for chunk in response:
                    delta = chunk.choices[0].delta
                    if not delta.content:
                        continue
                    streamed_chunks.append(delta.content)
                    yield delta.content
                _end_langsmith_trace(
                    trace_run,
                    text="".join(streamed_chunks),
                )
            logger.info(
                "llm_stream_complete",
                elapsed_s=round(time.monotonic() - start, 2),
                model=profile.model,
                task_type=task_type.value,
            )
            _track_call(
                task_type=task_type.value,
                model=profile.model,
                start=start,
                success=True,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "llm_stream_timeout",
                elapsed_s=round(time.monotonic() - start, 2),
                model=profile.model,
                task_type=task_type.value,
                timeout_s=profile.timeout_s,
                **_trace_log_fields(),
            )
            _track_call(task_type=task_type.value, model=profile.model, start=start, success=False, error="timeout")
            raise LLMTimeoutError(timeout_s=profile.timeout_s)
        except Exception as exc:
            _track_call(task_type=task_type.value, model=profile.model, start=start, success=False, error=str(exc))
            logger.error("llm_stream_failed", error=str(exc))
            raise LLMCallError(reason=str(exc)) from exc


async def acompletion_with_tools(
    messages: list[ChatMessage],
    *,
    tools: list[dict] | None = None,
    task_type: TaskType = TaskType.DEFAULT,
    **kwargs,
):
    """异步补全（支持工具调用）。

    与 acompletion() 的区别：
    - 返回完整的 LiteLLM Response 对象，因为调用方需要检查 tool_calls。
    - 可传入 ``tools`` 参数（OpenAI function calling 格式）。

    Args:
        messages: 消息列表。
        tools: 工具定义列表（OpenAI 格式），为空时行为等同于普通补全。
        task_type: 任务类型，用于模型路由。
        **kwargs: 透传给 LiteLLM 的其他参数。

    Returns:
        litellm.ModelResponse — 包含 choices[0].message.content 和/或
        choices[0].message.tool_calls。
    """

    settings = get_settings()
    api_key = settings.require_llm_api_key()
    profile = get_task_profile(task_type)
    last_error: Exception | None = None
    call_started_at = time.monotonic()

    async with _get_semaphore():
        for attempt in range(1, profile.max_retries + 1):
            start = time.monotonic()
            call_kwargs = _build_completion_kwargs(
                profile=profile,
                settings=settings,
                api_key=api_key,
                messages=messages,
                extra_kwargs=dict(kwargs),
            )
            if tools:
                call_kwargs["tools"] = tools
            logger.info(
                "llm_tools_started",
                attempt=attempt,
                model=profile.model,
                task_type=task_type.value,
                tool_count=len(tools) if tools else 0,
            )
            try:
                with langsmith_trace(
                    name="llm.acompletion_with_tools",
                    run_type="llm",
                    **_langsmith_trace_kwargs(
                        task_type=task_type,
                        model=profile.model,
                        mode="tools",
                        messages=messages,
                        attempt=attempt,
                        tools=tools,
                    ),
                ) as trace_run:
                    response = await asyncio.wait_for(
                        litellm.acompletion(**call_kwargs),
                        timeout=profile.timeout_s + 2,
                    )
                    prompt_t, completion_t, total_t = _extract_usage(response)
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
                    model=profile.model,
                    task_type=task_type.value,
                    has_tool_calls=bool(
                        getattr(response.choices[0].message, "tool_calls", None)
                    ),
                )
                _track_call(
                    task_type=task_type.value,
                    model=profile.model,
                    start=call_started_at,
                    success=True,
                    prompt_tokens=prompt_t,
                    completion_tokens=completion_t,
                    total_tokens=total_t,
                )
                return response
            except asyncio.TimeoutError:
                last_error = LLMTimeoutError(timeout_s=profile.timeout_s)
                logger.warning(
                    "llm_tools_timeout",
                    attempt=attempt,
                    model=profile.model,
                    task_type=task_type.value,
                    timeout_s=profile.timeout_s,
                    **_trace_log_fields(),
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "llm_tools_failed",
                    attempt=attempt,
                    model=profile.model,
                    task_type=task_type.value,
                    error=str(exc),
                    **_trace_log_fields(),
                )

            if attempt < profile.max_retries:
                await asyncio.sleep(attempt * 2)

    _track_call(
        task_type=task_type.value,
        model=profile.model,
        start=call_started_at,
        success=False,
        error=str(last_error),
    )
    if isinstance(last_error, LLMTimeoutError):
        raise last_error
    raise LLMCallError(reason=str(last_error)) from last_error
