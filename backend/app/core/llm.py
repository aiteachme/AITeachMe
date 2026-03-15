"""
统一 LLM 调用封装

所有 LLM 调用通过此模块进行，提供：
- acompletion()：异步补全，60s 超时，最多重试 3 次（递增退避）
- acompletion_structured()：Instructor 结构化输出，重试由本层统一处理
- acompletion_stream()：异步生成器，逐 token 产出

上层调用方（workflow、generator 等）不再自行重试 LLM，仅处理 success/fail。
"""

import asyncio
import time
from typing import AsyncGenerator, TypeVar

import instructor
import litellm
import structlog

from app.core.config import get_settings
from app.core.exceptions import LLMCallError, LLMTimeoutError
from app.schemas.llm import ChatMessage

logger = structlog.get_logger()

T = TypeVar("T")

_MAX_RETRIES = 3
_TIMEOUT_S = 60


async def acompletion(messages: list[ChatMessage], **kwargs) -> str:
    """异步 LLM 补全，60s 超时，最多重试 3 次（递增退避）。"""
    settings = get_settings()
    last_exc: Exception | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
        start = time.monotonic()
        try:
            response = await litellm.acompletion(
                model=f"openai/{settings.llm_model}",
                messages=messages,
                api_base=settings.llm_base_url,
                api_key=settings.llm_api_key,
                timeout=_TIMEOUT_S,
                **kwargs,
            )
            elapsed = time.monotonic() - start
            usage = getattr(response, "usage", None)
            logger.info(
                "llm_call",
                attempt=attempt,
                elapsed_s=round(elapsed, 2),
                usage=usage.model_dump() if usage else None,
            )
            return response.choices[0].message.content

        except asyncio.TimeoutError:
            elapsed = time.monotonic() - start
            logger.warning("llm_timeout", attempt=attempt, elapsed_s=round(elapsed, 2))
            last_exc = LLMTimeoutError(timeout_s=_TIMEOUT_S)

        except Exception as exc:
            elapsed = time.monotonic() - start
            logger.warning(
                "llm_call_failed",
                attempt=attempt,
                elapsed_s=round(elapsed, 2),
                error=str(exc),
            )
            last_exc = exc

        if attempt < _MAX_RETRIES:
            backoff = attempt * 2
            logger.info("llm_retry_backoff", next_attempt=attempt + 1, backoff_s=backoff)
            await asyncio.sleep(backoff)

    if isinstance(last_exc, LLMTimeoutError):
        raise last_exc
    raise LLMCallError(reason=str(last_exc)) from last_exc


async def acompletion_structured(
    response_model: type[T],
    messages: list[ChatMessage],
    **kwargs,
) -> T:
    """异步结构化输出，使用 Instructor。重试由本层统一处理。"""
    settings = get_settings()
    client = instructor.from_litellm(litellm.acompletion)
    last_exc: Exception | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
        start = time.monotonic()
        try:
            result = await client.chat.completions.create(
                model=f"openai/{settings.llm_model}",
                messages=messages,
                response_model=response_model,
                api_base=settings.llm_base_url,
                api_key=settings.llm_api_key,
                timeout=_TIMEOUT_S,
                max_retries=0,
                **kwargs,
            )
            elapsed = time.monotonic() - start
            logger.info(
                "llm_structured_call",
                attempt=attempt,
                elapsed_s=round(elapsed, 2),
                model=response_model.__name__,
            )
            return result

        except asyncio.TimeoutError:
            elapsed = time.monotonic() - start
            logger.warning("llm_structured_timeout", attempt=attempt, elapsed_s=round(elapsed, 2))
            last_exc = LLMTimeoutError(timeout_s=_TIMEOUT_S)

        except Exception as exc:
            elapsed = time.monotonic() - start
            logger.warning(
                "llm_structured_failed",
                attempt=attempt,
                elapsed_s=round(elapsed, 2),
                error=str(exc),
            )
            last_exc = exc

        if attempt < _MAX_RETRIES:
            backoff = attempt * 2
            logger.info("llm_structured_retry_backoff", next_attempt=attempt + 1, backoff_s=backoff)
            await asyncio.sleep(backoff)

    if isinstance(last_exc, LLMTimeoutError):
        raise last_exc
    raise LLMCallError(reason=str(last_exc)) from last_exc


async def acompletion_stream(messages: list[ChatMessage], **kwargs) -> AsyncGenerator[str, None]:
    """异步流式补全，逐 token 产出内容字符串。不重试。"""
    settings = get_settings()
    start = time.monotonic()
    try:
        response = await litellm.acompletion(
            model=f"openai/{settings.llm_model}",
            messages=messages,
            api_base=settings.llm_base_url,
            api_key=settings.llm_api_key,
            timeout=_TIMEOUT_S,
            stream=True,
            **kwargs,
        )
        async for chunk in response:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content

        elapsed = time.monotonic() - start
        logger.info("llm_stream_complete", elapsed_s=round(elapsed, 2))

    except asyncio.TimeoutError:
        elapsed = time.monotonic() - start
        logger.error("llm_stream_timeout", elapsed_s=round(elapsed, 2))
        raise LLMTimeoutError(timeout_s=_TIMEOUT_S)

    except Exception as exc:
        elapsed = time.monotonic() - start
        logger.error("llm_stream_error", elapsed_s=round(elapsed, 2), error=str(exc))
        raise LLMCallError(reason=str(exc)) from exc
