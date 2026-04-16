"""Produce a light, LLM-assisted digest of uploaded material.

The digest is reused by planner and docgen to keep prompt context short
while still giving the reason/primary tiers a faithful view of the real
document content instead of filenames and rule-based hints alone.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import structlog

from app.shared.infra.llm_support import acompletion
from app.shared.infra.llm_support.routing import TaskType
from app.workflows.digest.common.models import DigestMaterialContext, SourcePacket

logger = structlog.get_logger(__name__)

SHORT_THRESHOLD_CHARS = 20_000
CHUNK_SIZE_CHARS = 12_000
MAX_CHUNKS = 12


@dataclass(frozen=True)
class MaterialDigestResult:
    """Outcome of the light digest pass."""

    digest: str
    total_chars: int
    chunk_count: int
    llm_used: bool
    truncated: bool


def _render_concatenated_source(packets: list[SourcePacket]) -> str:
    parts: list[str] = []
    for packet in packets:
        content = (packet.normalized_content or "").strip()
        if not content:
            continue
        header = f"===== {packet.filename or f'file_{packet.file_id}'} ====="
        parts.append(f"{header}\n{content}")
    return "\n\n".join(parts).strip()


def _split_into_chunks(text: str, *, size: int, limit: int) -> list[str]:
    chunks: list[str] = []
    total = len(text)
    for start in range(0, total, size):
        if len(chunks) >= limit:
            break
        chunks.append(text[start : start + size])
    return chunks


def _summary_prompt(chunk: str, *, chunk_index: int, chunk_total: int) -> str:
    position = (
        f"（共 {chunk_total} 段，这是第 {chunk_index + 1} 段）"
        if chunk_total > 1
        else ""
    )
    return (
        "你是学习资料速览员。请用中文对下面这段用户上传的学习资料做极简要点摘要。"
        f"{position}\n"
        "约束：\n"
        "1. 350-500 字，不要罗列原文句子。\n"
        "2. 只输出要点型段落，不要小标题/列表/引用/代码块。\n"
        "3. 覆盖：核心主题、关键概念或公式、出现的题型或方法、难度线索。\n"
        "4. 不要推测未给出的内容，不要写学习建议。\n\n"
        "资料片段：\n"
        f"{chunk}"
    )


async def _summarize_chunk(chunk: str, *, chunk_index: int, chunk_total: int) -> str:
    try:
        text = await acompletion(
            [{"role": "user", "content": _summary_prompt(chunk, chunk_index=chunk_index, chunk_total=chunk_total)}],
            task_type=TaskType.SUMMARIZE,
            tier_override="light",
            temperature=0.2,
            max_tokens=720,
        )
    except Exception:
        logger.exception(
            "material_digest_chunk_failed",
            chunk_index=chunk_index,
            chunk_total=chunk_total,
        )
        return ""
    return (text or "").strip()


async def build_material_digest(
    material_context: DigestMaterialContext,
) -> MaterialDigestResult:
    """Return a compact digest of the uploaded material.

    短路策略：总字符数 < SHORT_THRESHOLD_CHARS 时直接拼原文；
    超过阈值则按 CHUNK_SIZE_CHARS 分片，最多 MAX_CHUNKS 片并行走 light 模型。
    """

    concatenated = _render_concatenated_source(list(material_context.source_documents))
    total = len(concatenated)
    if not concatenated:
        return MaterialDigestResult(digest="", total_chars=0, chunk_count=0, llm_used=False, truncated=False)

    if total < SHORT_THRESHOLD_CHARS:
        return MaterialDigestResult(
            digest=concatenated,
            total_chars=total,
            chunk_count=1,
            llm_used=False,
            truncated=False,
        )

    chunks = _split_into_chunks(concatenated, size=CHUNK_SIZE_CHARS, limit=MAX_CHUNKS)
    truncated = total > len(chunks) * CHUNK_SIZE_CHARS
    summaries = await asyncio.gather(
        *(
            _summarize_chunk(chunk, chunk_index=index, chunk_total=len(chunks))
            for index, chunk in enumerate(chunks)
        )
    )
    kept = [summary for summary in summaries if summary]
    if not kept:
        fallback = concatenated[: CHUNK_SIZE_CHARS]
        return MaterialDigestResult(
            digest=fallback,
            total_chars=total,
            chunk_count=len(chunks),
            llm_used=True,
            truncated=True,
        )

    if len(kept) == 1:
        digest_text = kept[0]
    else:
        digest_text = "\n\n".join(
            f"段{index + 1}：{summary}" for index, summary in enumerate(kept)
        )
    return MaterialDigestResult(
        digest=digest_text,
        total_chars=total,
        chunk_count=len(chunks),
        llm_used=True,
        truncated=truncated,
    )


__all__ = [
    "CHUNK_SIZE_CHARS",
    "MAX_CHUNKS",
    "MaterialDigestResult",
    "SHORT_THRESHOLD_CHARS",
    "build_material_digest",
]
