"""
Embedding 统一封装

使用 LiteLLM 批量计算文本嵌入向量。
embedding_model 从 Settings 读取，embedding_dim 由模型自动推导。
"""

import time

import litellm
import structlog

from app.core.config import get_settings
from app.core.exceptions import LLMCallError

logger = structlog.get_logger()


async def aembed_texts(texts: list[str]) -> list[list[float]]:
    """批量嵌入文本列表，返回浮点向量列表。

    Args:
        texts: 待嵌入的文本列表，不可为空。

    Returns:
        与 texts 等长的向量列表，每个向量维度由 embedding_model 决定。

    Raises:
        LLMCallError: embedding 调用失败时抛出。
    """
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
        elapsed = time.monotonic() - start

        vectors = [item["embedding"] for item in response.data]

        usage = getattr(response, "usage", None)
        logger.info(
            "embedding_call",
            elapsed_s=round(elapsed, 2),
            num_texts=len(texts),
            dim=len(vectors[0]) if vectors else 0,
            usage=usage.model_dump() if usage else None,
        )
        return vectors

    except Exception as exc:
        elapsed = time.monotonic() - start
        logger.error("embedding_call_failed", elapsed_s=round(elapsed, 2), error=str(exc))
        raise LLMCallError(reason=f"Embedding 调用失败：{exc}") from exc
