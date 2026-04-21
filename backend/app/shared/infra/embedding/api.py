"""统一的 Embedding 调用封装。

支持：
- 自动分批处理（防止超限）
- 自动兼容不同 API 提供商（DashScope / OpenAI / 硅基流动等）
- 失败自动降级重试
- 调用追踪
"""

from __future__ import annotations

import asyncio
import time

import structlog

from app.shared.infra.settings import PROJECT_SETTINGS_ENV_NAME, get_settings
from app.shared.infra.env_support import get_env
from app.shared.infra.exceptions import LLMCallError, MissingLLMApiKeyError
from app.shared.infra.llm_support.litellm_loader import load_litellm

logger = structlog.get_logger()
litellm = load_litellm()

# 全局：让 litellm 尽可能丢弃不支持的参数
litellm.drop_params = True


def _build_model_name(embedding_model: str) -> str:
    """构建 litellm 路由所需的 model 名称。

    如果用户已经在 EMBEDDING_MODEL 中写好了 provider 前缀
    （如 ``openai/text-embedding-3-small`` 或 ``dashscope/qwen3-embedding-0.6b``），
    就直接使用；否则默认加 ``openai/`` 前缀，以兼容 OpenAI 兼容协议
    （DashScope compatible-mode / SiliconFlow / aihubmix 等）。
    """
    if "/" in embedding_model:
        return embedding_model
    return f"openai/{embedding_model}"


async def _call_embedding(
    model: str,
    batch: list[str],
    api_base: str,
    api_key: str,
) -> list[list[float]]:
    """调用 litellm embedding，自动处理 encoding_format 兼容性。

    策略：
    1. 先用 encoding_format="float" 调用（大多数 API 都支持）
    2. 如果报 400（参数不支持），降级不带 encoding_format 重试
    """
    try:
        response = await litellm.aembedding(
            model=model,
            input=batch,
            api_base=api_base,
            api_key=api_key,
            encoding_format="float",
        )
        return [item["embedding"] for item in response.data]
    except litellm.exceptions.BadRequestError as exc:
        error_text = str(exc)
        # encoding_format 不被支持，降级重试
        if "encoding_format" in error_text:
            logger.info(
                "embedding_encoding_format_fallback",
                reason="API 不支持 encoding_format 参数，降级重试",
            )
            response = await litellm.aembedding(
                model=model,
                input=batch,
                api_base=api_base,
                api_key=api_key,
            )
            return [item["embedding"] for item in response.data]
        if (
            "Incorrect model ID" in error_text
            or "do not have permission to use this model" in error_text
        ):
            configured_model = model.split("/", 1)[1] if "/" in model else model
            raise LLMCallError(
                reason=(
                    f"Embedding 模型 `{configured_model}` 在当前供应商不可用或无权限。"
                    f"请通过 {PROJECT_SETTINGS_ENV_NAME} 指向的外部项目配置文件，或通过本地设置页 / system runtime settings，将 `models.embedding` 改为账号可用模型后重启后端。"
                    f"当前 LLM_BASE_URL={api_base}。"
                    "常见可选：`text-embedding-3-small`（OpenAI 兼容）或 `text-embedding-v4`（DashScope）。"
                )
            ) from exc
        raise


async def aembed_texts(
    texts: list[str],
    *,
    batch_size: int | None = None,
) -> list[list[float]]:
    """批量生成文本向量，自动分批处理。

    Args:
        texts: 待向量化的文本列表。
        batch_size: 每批大小（默认从运行时 settings 读取）。
    """

    if not texts:
        return []

    settings = get_settings()
    api_key = (get_env("LLM_API_KEY") or "").strip()
    if not api_key:
        raise MissingLLMApiKeyError()
    batch_size = batch_size or settings.embedding.batch_size
    model = _build_model_name(settings.models.embedding)
    api_base = (
        get_env("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    start = time.monotonic()

    all_vectors: list[list[float]] = []
    total_batches = (len(texts) + batch_size - 1) // batch_size

    # Run batches concurrently (up to 4 at a time) for better throughput
    max_concurrent = min(total_batches, 4)
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _embed_batch(batch_idx: int) -> tuple[int, list[list[float]]]:
        batch_start = batch_idx * batch_size
        batch_end = min(batch_start + batch_size, len(texts))
        batch = texts[batch_start:batch_end]
        async with semaphore:
            try:
                batch_vectors = await _call_embedding(
                    model=model,
                    batch=batch,
                    api_base=api_base,
                    api_key=api_key,
                )
                return batch_idx, batch_vectors
            except LLMCallError as exc:
                logger.error(
                    "embedding_batch_failed",
                    batch_idx=batch_idx,
                    batch_size=len(batch),
                    model=model,
                    error=str(exc),
                )
                raise
            except Exception as exc:
                logger.error(
                    "embedding_batch_failed",
                    batch_idx=batch_idx,
                    batch_size=len(batch),
                    model=model,
                    error=str(exc),
                )
                raise LLMCallError(reason=f"Embedding 调用失败（批次 {batch_idx + 1}/{total_batches}）：{exc}") from exc

    if total_batches <= 1:
        # Single batch — no concurrency overhead
        _, vectors = await _embed_batch(0)
        all_vectors = vectors
    else:
        results = await asyncio.gather(*(_embed_batch(i) for i in range(total_batches)))
        # Re-order by batch index
        results_sorted = sorted(results, key=lambda r: r[0])
        for _, vectors in results_sorted:
            all_vectors.extend(vectors)

    logger.info(
        "embedding_call_complete",
        elapsed_s=round(time.monotonic() - start, 2),
        text_count=len(texts),
        batch_count=total_batches,
        model=model,
        embedding_dim=len(all_vectors[0]) if all_vectors else 0,
    )
    return all_vectors
