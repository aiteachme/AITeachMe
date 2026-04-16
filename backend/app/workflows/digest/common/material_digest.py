"""Produce a light, per-file digest of uploaded material."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import structlog

from app.shared.infra.llm_support import acompletion
from app.shared.infra.llm_support.routing import TaskType
from app.workflows.digest.common.models import DigestMaterialContext, SourcePacket

logger = structlog.get_logger(__name__)

FILE_CONTEXT_CHARS = 10_000


@dataclass(frozen=True)
class MaterialDigestResult:
    """Outcome of the light digest pass."""

    digest: str
    total_chars: int
    source_count: int
    llm_used: bool
    truncated: bool


def _source_label(packet: SourcePacket, *, index: int) -> str:
    return packet.filename or f"file_{packet.file_id or index + 1}"


def _summary_prompt(packet: SourcePacket, *, content: str, index: int, total: int, truncated: bool) -> str:
    label = _source_label(packet, index=index)
    truncation_note = "这份资料较长，下面只截取前 10000 字用于速览。" if truncated else "下面是这份资料的全文或主要正文。"
    return (
        "你是学习资料速览员。请用中文单独概括下面这一份用户上传资料。"
        f"（共 {total} 份，这是第 {index + 1} 份：{label}）\n"
        f"{truncation_note}\n"
        "约束：\n"
        "1. 350-500 字，不要罗列原文句子。\n"
        "2. 只输出要点型段落，不要小标题/列表/引用/代码块。\n"
        "3. 覆盖：核心主题、关键概念或公式、出现的题型或方法、难度线索、明显缺口。\n"
        "4. 不要推测未给出的内容，不要写学习建议。\n\n"
        f"资料内容：\n{content}"
    )


async def _summarize_packet(packet: SourcePacket, *, index: int, total: int) -> tuple[str, bool]:
    content = (packet.normalized_content or "").strip()
    if not content:
        return "", False
    truncated = len(content) > FILE_CONTEXT_CHARS
    context = content[:FILE_CONTEXT_CHARS]
    try:
        text = await acompletion(
            [
                {
                    "role": "user",
                    "content": _summary_prompt(
                        packet,
                        content=context,
                        index=index,
                        total=total,
                        truncated=truncated,
                    ),
                }
            ],
            task_type=TaskType.SUMMARIZE,
            tier_override="light",
            temperature=0.2,
            max_tokens=720,
        )
    except Exception:
        logger.exception(
            "material_digest_source_failed",
            source_index=index,
            source_total=total,
            filename=packet.filename,
        )
        return context, truncated
    summary = (text or "").strip()
    return summary or context, truncated


async def build_material_digest(
    material_context: DigestMaterialContext,
) -> MaterialDigestResult:
    """Return a compact digest of uploaded material.

    每个文件独立进入 light 模型摘要，并行执行；不再先拼接所有文件。
    单个文件最多给模型前 FILE_CONTEXT_CHARS 字，避免超长文件拖垮 planner。
    """

    packets = [
        packet
        for packet in list(material_context.source_documents)
        if (packet.normalized_content or "").strip()
    ]
    if not packets:
        return MaterialDigestResult(digest="", total_chars=0, source_count=0, llm_used=False, truncated=False)

    total_chars = sum(len((packet.normalized_content or "").strip()) for packet in packets)
    results = await asyncio.gather(
        *(
            _summarize_packet(packet, index=index, total=len(packets))
            for index, packet in enumerate(packets)
        )
    )
    sections = [
        f"资料{index + 1}（{_source_label(packet, index=index)}）：{summary}"
        for index, (packet, (summary, _truncated)) in enumerate(zip(packets, results, strict=False))
        if summary
    ]
    return MaterialDigestResult(
        digest="\n\n".join(sections),
        total_chars=total_chars,
        source_count=len(packets),
        llm_used=True,
        truncated=any(truncated for _summary, truncated in results),
    )


__all__ = [
    "FILE_CONTEXT_CHARS",
    "MaterialDigestResult",
    "build_material_digest",
]
