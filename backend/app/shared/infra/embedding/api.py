"""统一的 Embedding 调用封装。

支持：
- 自动分批处理（防止超限）
- 自动兼容不同 API 提供商（DashScope / OpenAI / 硅基流动等）
- 失败自动降级重试
- 调用追踪
"""

from __future__ import annotations

import time
from urllib.parse import urlparse, urlunparse

import structlog

from app.shared.infra.embedding.defaults import DEFAULT_EMBEDDING_BATCH_SIZE
from app.shared.infra.exceptions import LLMCallError, MissingLLMApiKeyError
from app.shared.infra.llm_support.common import (
    apply_provider_extra_headers,
    build_completion_contexts,
    build_litellm_provider_kwargs,
    get_llm_concurrency_limiter,
    get_llm_runtime_snapshot,
)
from app.shared.infra.llm_support.litellm_loader import load_litellm
from app.shared.infra.llm_support import run_llm_tasks
from app.shared.infra.observability.trace import trace_substep

logger = structlog.get_logger()


def _normalize_embedding_api_base(
    api_base: str,
    *,
    provider_kwargs: dict[str, object],
) -> str:
    """Prefer the conventional /v1 root for OpenAI-compatible embedding APIs."""

    normalized = (api_base or "").strip()
    if not normalized:
        return normalized
    if provider_kwargs.get("custom_llm_provider") != "openai":
        return normalized

    try:
        parsed = urlparse(normalized)
    except Exception:
        return normalized
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return normalized
    if (parsed.path or "").rstrip("/"):
        return normalized.rstrip("/")
    return urlunparse(parsed._replace(path="/v1")).rstrip("/")


async def _call_embedding(
    model: str,
    batch: list[str],
    api_base: str,
    api_key: str | None,
    provider: str | None = None,
    api_version: str | None = None,
) -> list[list[float]]:
    """调用 litellm embedding，自动处理 encoding_format 兼容性。

    策略：
    1. 先用 encoding_format="float" 调用（大多数 API 都支持）
    2. 如果报 400（参数不支持），降级不带 encoding_format 重试
    """
    litellm = load_litellm()
    # 全局：让 litellm 尽可能丢弃不支持的参数
    litellm.drop_params = True
    provider_kwargs = build_litellm_provider_kwargs(
        model,
        runtime_provider=provider,
        api_version=api_version,
    )
    normalized_api_base = _normalize_embedding_api_base(
        api_base,
        provider_kwargs=provider_kwargs,
    )
    try:
        request_kwargs = {
            "model": model,
            "input": batch,
            "api_base": normalized_api_base,
            "encoding_format": "float",
            **provider_kwargs,
        }
        if api_key is not None:
            request_kwargs["api_key"] = api_key
        apply_provider_extra_headers(request_kwargs)
        async with get_llm_concurrency_limiter():
            response = await litellm.aembedding(
                **request_kwargs,
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
            fallback_kwargs = {
                "model": model,
                "input": batch,
                "api_base": normalized_api_base,
                **provider_kwargs,
            }
            if api_key is not None:
                fallback_kwargs["api_key"] = api_key
            apply_provider_extra_headers(fallback_kwargs)
            async with get_llm_concurrency_limiter():
                response = await litellm.aembedding(**fallback_kwargs)
            return [item["embedding"] for item in response.data]
        if (
            "Incorrect model ID" in error_text
            or "do not have permission to use this model" in error_text
        ):
            configured_model = model.split("/", 1)[1] if "/" in model else model
            raise LLMCallError(
                reason=(
                    f"Embedding 模型 `{configured_model}` 在当前供应商不可用或无权限。"
                    "请在本地设置页将 `models.embedding` 改为当前网关/账号可用的 embedding 模型。"
                    "保存后对下一次请求或下一次构建生效；已经开始的构建不会中途切换。"
                    f"当前 LLM_BASE_URL={api_base}。"
                    "可优先参考当前供应商控制台的 embedding 模型列表。"
                )
            ) from exc
        raise


async def aembed_texts(
    texts: list[str],
    *,
    batch_size: int | None = None,
    model: str | None = None,
    max_concurrent: int | None = None,
    soft_fail: bool = False,
) -> list[list[float]]:
    """批量生成文本向量，自动分批处理。

    Args:
        texts: 待向量化的文本列表。
        batch_size: 每批大小（默认从运行时 settings 读取）。
        max_concurrent: 多批次向量化时的上层并发窗口；None 表示沿用全局上限。
        soft_fail: 当 embedding 调用失败时，是否记录 warning 并返回空列表。
    """

    if not texts:
        return []

    snapshot = get_llm_runtime_snapshot()
    settings = snapshot.settings
    batch_size = batch_size or DEFAULT_EMBEDDING_BATCH_SIZE
    resolved_model = str(model or settings.models.embedding or "").strip()
    if not resolved_model:
        if soft_fail:
            logger.info(
                "embedding_skipped_unconfigured",
                text_count=len(texts),
                reason="models.embedding is empty",
            )
            return []
        raise LLMCallError(reason="models.embedding is not configured")
    context = build_completion_contexts(task_type="embedding", model=resolved_model)[0]
    api_base = context.base_url or "https://api.openai.com/v1"
    start = time.monotonic()

    all_vectors: list[list[float]] = []
    total_batches = (len(texts) + batch_size - 1) // batch_size

    async def _embed_batch(batch_idx: int) -> tuple[int, list[list[float]]]:
        batch_start = batch_idx * batch_size
        batch_end = min(batch_start + batch_size, len(texts))
        batch = texts[batch_start:batch_end]
        try:
            batch_vectors = await _call_embedding(
                model=resolved_model,
                batch=batch,
                api_base=api_base,
                api_key=context.api_key,
                provider=context.provider,
                api_version=context.api_version,
            )
            return batch_idx, batch_vectors
        except LLMCallError as exc:
            log_method = logger.warning if soft_fail else logger.error
            log_method(
                "embedding_batch_soft_failed" if soft_fail else "embedding_batch_failed",
                batch_idx=batch_idx,
                batch_size=len(batch),
                model=resolved_model,
                endpoint_role=context.endpoint_role,
                error=str(exc),
            )
            raise
        except Exception as exc:
            log_method = logger.warning if soft_fail else logger.error
            log_method(
                "embedding_batch_soft_failed" if soft_fail else "embedding_batch_failed",
                batch_idx=batch_idx,
                batch_size=len(batch),
                model=resolved_model,
                endpoint_role=context.endpoint_role,
                error=str(exc),
            )
            raise LLMCallError(reason=f"Embedding 调用失败（批次 {batch_idx + 1}/{total_batches}）：{exc}") from exc

    with trace_substep(
        "Embedding：批量生成",
        run_type="embedding",
        metadata={
            "text_count": len(texts),
            "batch_count": total_batches,
            "batch_size": batch_size,
            "max_concurrent": max_concurrent or 0,
            "model": resolved_model,
            "endpoint_role": context.endpoint_role,
        },
        tags=["embedding:batch"],
        inputs={
            "text_count": len(texts),
            "batch_count": total_batches,
            "batch_size": batch_size,
            "max_concurrent": max_concurrent or 0,
        },
    ) as trace_run:
        try:
            if total_batches <= 1:
                # Single batch, no fan-out overhead.
                _, vectors = await _embed_batch(0)
                all_vectors = vectors
            else:
                results = await run_llm_tasks(
                    range(total_batches),
                    _embed_batch,
                    max_concurrent=max_concurrent,
                )
                # Re-order by batch index.
                results_sorted = sorted(results, key=lambda r: r[0])
                for _, vectors in results_sorted:
                    all_vectors.extend(vectors)
            if trace_run is not None:
                trace_run.end(
                    outputs={
                        "status": "completed",
                        "elapsed_s": round(time.monotonic() - start, 2),
                        "text_count": len(texts),
                        "batch_count": total_batches,
                        "model": resolved_model,
                        "endpoint_role": context.endpoint_role,
                        "embedding_dim": len(all_vectors[0]) if all_vectors else 0,
                    }
                )
        except (MissingLLMApiKeyError, LLMCallError) as exc:
            if trace_run is not None:
                trace_run.end(
                    outputs={
                        "status": "soft_failed" if soft_fail else "failed",
                        "text_count": len(texts),
                        "batch_count": total_batches,
                        "model": resolved_model,
                        "error": str(exc),
                    }
                )
            if not soft_fail:
                raise
            logger.warning(
                "embedding_call_soft_failed",
                text_count=len(texts),
                batch_count=total_batches,
                model=resolved_model,
                endpoint_role=context.endpoint_role,
                error=str(exc),
            )
            return []

    logger.info(
        "embedding_call_complete",
        elapsed_s=round(time.monotonic() - start, 2),
        text_count=len(texts),
        batch_count=total_batches,
        model=resolved_model,
        endpoint_role=context.endpoint_role,
        embedding_dim=len(all_vectors[0]) if all_vectors else 0,
    )
    return all_vectors
