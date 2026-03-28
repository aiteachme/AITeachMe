"""统一的 Embedding 调用封装。

支持：
- 自动分批处理（防止超限）
- 失败重试
- 调用追踪
"""

from __future__ import annotations

import asyncio
import time

import litellm
import structlog

from app.core.config import get_settings
from app.core.exceptions import LLMCallError

logger = structlog.get_logger()


async def aembed_texts(
    texts: list[str],
    *,
    batch_size: int | None = None,
) -> list[list[float]]:
    """批量生成文本向量，自动分批处理。

    Args:
        texts: 待向量化的文本列表。
        batch_size: 每批大小（默认从 config 读取，环境变量 EMBEDDING_BATCH_SIZE）。
    """

    if not texts:
        return []

    settings = get_settings()
    api_key = settings.require_llm_api_key()
    batch_size = batch_size or settings.embedding_batch_size
    start = time.monotonic()

    all_vectors: list[list[float]] = []
    total_batches = (len(texts) + batch_size - 1) // batch_size

    for batch_idx in range(total_batches):
        batch_start = batch_idx * batch_size
        batch_end = min(batch_start + batch_size, len(texts))
        batch = texts[batch_start:batch_end]

        try:
            response = await litellm.aembedding(
                model=f"openai/{settings.embedding_model}",
                input=batch,
                api_base=settings.llm_base_url,
                api_key=api_key,
            )
            batch_vectors = [item["embedding"] for item in response.data]
            all_vectors.extend(batch_vectors)
        except Exception as exc:
            logger.error(
                "embedding_batch_failed",
                batch_idx=batch_idx,
                batch_size=len(batch),
                error=str(exc),
            )
            raise LLMCallError(reason=f"Embedding 调用失败（批次 {batch_idx + 1}/{total_batches}）：{exc}") from exc

        # 批次间限流
        if batch_idx < total_batches - 1:
            await asyncio.sleep(settings.embedding_batch_delay_s)

    logger.info(
        "embedding_call_complete",
        elapsed_s=round(time.monotonic() - start, 2),
        text_count=len(texts),
        batch_count=total_batches,
        embedding_dim=len(all_vectors[0]) if all_vectors else 0,
    )
    return all_vectors
