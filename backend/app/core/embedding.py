"""统一的 Embedding 调用封装。"""

from __future__ import annotations

import time

import litellm
import structlog

from app.core.config import get_settings
from app.core.exceptions import LLMCallError

logger = structlog.get_logger()


async def aembed_texts(texts: list[str]) -> list[list[float]]:
    """批量生成文本向量。"""

    if not texts:
        return []

    settings = get_settings()
    api_key = settings.require_llm_api_key()
    start = time.monotonic()

    try:
        response = await litellm.aembedding(
            model=f"openai/{settings.embedding_model}",
            input=texts,
            api_base=settings.llm_base_url,
            api_key=api_key,
        )
        vectors = [item["embedding"] for item in response.data]
        logger.info(
            "embedding_call_complete",
            elapsed_s=round(time.monotonic() - start, 2),
            text_count=len(texts),
            embedding_dim=len(vectors[0]) if vectors else 0,
        )
        return vectors
    except Exception as exc:
        logger.error("embedding_call_failed", error=str(exc))
        raise LLMCallError(reason=f"Embedding 调用失败：{exc}") from exc
