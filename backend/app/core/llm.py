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
    model_name = f"openai/{profile.model}"
    last_error: Exception | None = None

    async with _get_semaphore():
        for attempt in range(1, profile.max_retries + 1):
            start = time.monotonic()
            try:
                response = await litellm.acompletion(
                    model=model_name,
                    messages=messages,
                    api_base=settings.llm_base_url,
                    api_key=api_key,
                    timeout=profile.timeout_s,
                    temperature=kwargs.pop("temperature", profile.temperature),
                    **kwargs,
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
            except Exception as exc:
                last_error = exc
                logger.warning("llm_completion_failed", attempt=attempt, error=str(exc))

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

    for attempt in range(1, profile.max_retries + 1):
        start = time.monotonic()
        try:
            result = await client.chat.completions.create(
                model=model_name,
                messages=messages,
                response_model=response_model,
                api_base=settings.llm_base_url,
                api_key=api_key,
                timeout=profile.timeout_s,
                max_retries=0,
                temperature=kwargs.pop("temperature", profile.temperature),
                **kwargs,
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
        except Exception as exc:
            last_error = exc
            logger.warning("llm_structured_failed", attempt=attempt, error=str(exc))

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
    model_name = f"openai/{profile.model}"
    start = time.monotonic()

    try:
        response = await litellm.acompletion(
            model=model_name,
            messages=messages,
            api_base=settings.llm_base_url,
            api_key=api_key,
            timeout=profile.timeout_s,
            stream=True,
            temperature=kwargs.pop("temperature", profile.temperature),
            **kwargs,
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
        _track_call(task_type=task_type.value, model=profile.model, start=start, success=False, error="timeout")
        raise LLMTimeoutError(timeout_s=profile.timeout_s)
    except Exception as exc:
        _track_call(task_type=task_type.value, model=profile.model, start=start, success=False, error=str(exc))
        logger.error("llm_stream_failed", error=str(exc))
        raise LLMCallError(reason=str(exc)) from exc
