"""统一的 LLM 调用封装。

支持：
- 按任务类型选择模型（model_router）
- 调用追踪与统计（tracing）
- 文本补全 / 结构化补全 / 流式补全
"""

from __future__ import annotations

import asyncio
import time
from typing import AsyncGenerator, TypeVar

import litellm
import structlog
try:
    import instructor
except ModuleNotFoundError:  # pragma: no cover - optional dependency in local dev
    instructor = None

from app.core.tracing import LLMCallRecord, get_tracker
from app.core.config import get_settings
from app.core.exceptions import LLMCallError, LLMTimeoutError
from app.core.model_router import TaskType, get_task_profile
from app.schemas.llm import ChatMessage

logger = structlog.get_logger()

T = TypeVar("T")

# 保留原始常量作为兜底
_MAX_RETRIES = 3
_TIMEOUT_S = 60

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

    record = LLMCallRecord(
        task_type=task_type,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        latency_s=round(time.monotonic() - start, 3),
        success=success,
        error=error,
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
                response = await asyncio.wait_for(
                    litellm.acompletion(**call_kwargs),
                    timeout=profile.timeout_s + 2,
                )
                prompt_t, completion_t, total_t = _extract_usage(response)
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
                    start=start,
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
                )

            if attempt < profile.max_retries:
                await asyncio.sleep(attempt * 2)

    _track_call(
        task_type=task_type.value,
        model=profile.model,
        start=time.monotonic(),
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
        **kwargs: 透传给 Instructor 的其他参数。
    """

    settings = get_settings()
    api_key = settings.require_llm_api_key()
    profile = get_task_profile(task_type)
    model_name = f"openai/{profile.model}"
    if instructor is None:
        raise LLMCallError(reason="instructor is not installed")
    client = instructor.from_litellm(litellm.acompletion)
    last_error: Exception | None = None

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
            )
            try:
                result = await asyncio.wait_for(
                    client.chat.completions.create(
                        response_model=response_model,
                        max_retries=0,
                        **call_kwargs,
                    ),
                    timeout=profile.timeout_s + 2,
                )
                logger.info(
                    "llm_structured_complete",
                    attempt=attempt,
                    elapsed_s=round(time.monotonic() - start, 2),
                    response_model=response_model.__name__,
                    model=profile.model,
                    task_type=task_type.value,
                )
                _track_call(
                    task_type=task_type.value,
                    model=profile.model,
                    start=start,
                    success=True,
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
                )

            if attempt < profile.max_retries:
                await asyncio.sleep(attempt * 2)

    _track_call(
        task_type=task_type.value,
        model=profile.model,
        start=time.monotonic(),
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
            response = await asyncio.wait_for(
                litellm.acompletion(**call_kwargs),
                timeout=profile.timeout_s + 2,
            )
            async for chunk in response:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield delta.content
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
                response = await asyncio.wait_for(
                    litellm.acompletion(**call_kwargs),
                    timeout=profile.timeout_s + 2,
                )
                prompt_t, completion_t, total_t = _extract_usage(response)
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
                    start=start,
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
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "llm_tools_failed",
                    attempt=attempt,
                    model=profile.model,
                    task_type=task_type.value,
                    error=str(exc),
                )

            if attempt < profile.max_retries:
                await asyncio.sleep(attempt * 2)

    _track_call(
        task_type=task_type.value,
        model=profile.model,
        start=time.monotonic(),
        success=False,
        error=str(last_error),
    )
    if isinstance(last_error, LLMTimeoutError):
        raise last_error
    raise LLMCallError(reason=str(last_error)) from last_error

