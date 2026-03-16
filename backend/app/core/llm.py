"""统一的 LLM 调用封装。"""

from __future__ import annotations

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
    """异步文本补全。"""

    settings = get_settings()
    api_key = settings.require_llm_api_key()
    last_error: Exception | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
        start = time.monotonic()
        try:
            response = await litellm.acompletion(
                model=f"openai/{settings.llm_model}",
                messages=messages,
                api_base=settings.llm_base_url,
                api_key=api_key,
                timeout=_TIMEOUT_S,
                **kwargs,
            )
            logger.info("llm_completion_complete", attempt=attempt, elapsed_s=round(time.monotonic() - start, 2))
            return response.choices[0].message.content
        except asyncio.TimeoutError:
            last_error = LLMTimeoutError(timeout_s=_TIMEOUT_S)
        except Exception as exc:
            last_error = exc
            logger.warning("llm_completion_failed", attempt=attempt, error=str(exc))

        if attempt < _MAX_RETRIES:
            await asyncio.sleep(attempt * 2)

    if isinstance(last_error, LLMTimeoutError):
        raise last_error
    raise LLMCallError(reason=str(last_error)) from last_error


async def acompletion_structured(
    response_model: type[T],
    messages: list[ChatMessage],
    **kwargs,
) -> T:
    """异步结构化补全。"""

    settings = get_settings()
    api_key = settings.require_llm_api_key()
    client = instructor.from_litellm(litellm.acompletion)
    last_error: Exception | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
        start = time.monotonic()
        try:
            result = await client.chat.completions.create(
                model=f"openai/{settings.llm_model}",
                messages=messages,
                response_model=response_model,
                api_base=settings.llm_base_url,
                api_key=api_key,
                timeout=_TIMEOUT_S,
                max_retries=0,
                **kwargs,
            )
            logger.info(
                "llm_structured_complete",
                attempt=attempt,
                elapsed_s=round(time.monotonic() - start, 2),
                response_model=response_model.__name__,
            )
            return result
        except asyncio.TimeoutError:
            last_error = LLMTimeoutError(timeout_s=_TIMEOUT_S)
        except Exception as exc:
            last_error = exc
            logger.warning("llm_structured_failed", attempt=attempt, error=str(exc))

        if attempt < _MAX_RETRIES:
            await asyncio.sleep(attempt * 2)

    if isinstance(last_error, LLMTimeoutError):
        raise last_error
    raise LLMCallError(reason=str(last_error)) from last_error


async def acompletion_stream(messages: list[ChatMessage], **kwargs) -> AsyncGenerator[str, None]:
    """异步流式补全。"""

    settings = get_settings()
    api_key = settings.require_llm_api_key()
    start = time.monotonic()

    try:
        response = await litellm.acompletion(
            model=f"openai/{settings.llm_model}",
            messages=messages,
            api_base=settings.llm_base_url,
            api_key=api_key,
            timeout=_TIMEOUT_S,
            stream=True,
            **kwargs,
        )
        async for chunk in response:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content
        logger.info("llm_stream_complete", elapsed_s=round(time.monotonic() - start, 2))
    except asyncio.TimeoutError:
        raise LLMTimeoutError(timeout_s=_TIMEOUT_S)
    except Exception as exc:
        logger.error("llm_stream_failed", error=str(exc))
        raise LLMCallError(reason=str(exc)) from exc
