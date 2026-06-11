"""Build raw planner material context from uploaded material."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from pydantic import BaseModel, Field
import structlog

from app.shared.infra.llm_support import acompletion_with_fallback, run_llm_tasks
from app.shared.infra.llm_support.context_window import ContextWindowManager
from app.shared.infra.llm_support.litellm_loader import load_litellm
from app.workflows.digest.common.models import DigestMaterialContext, SectionPacket, SourcePacket
from app.workflows.digest.planner.lib.model_policy import (
    PlannerModelStep,
    planner_completion_kwargs_with_metadata,
)

logger = structlog.get_logger(__name__)

_FULL_CONTEXT_MAX_CHARS = 72_000
_FULL_CONTEXT_MAX_TOKENS = 28_000
_BATCH_TARGET_CHARS = 24_000
_BATCH_EXCERPT_MAX_CHARS = 18_000


class _MaterialBatchSummary(BaseModel):
    """Structured summary for one planner material batch."""

    summary: str = ""
    topics: list[str] = Field(default_factory=list)
    structure_hints: list[str] = Field(default_factory=list)
    high_value_sections: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class _MaterialSectionBatch:
    """One ordered source section batch used by Planner material map-reduce."""

    batch_index: int
    total_batches: int
    sections: list[SectionPacket]


@dataclass(frozen=True)
class MaterialDigestResult:
    """Outcome of the raw context packing pass."""

    digest: str
    total_chars: int
    total_tokens: int
    source_count: int
    llm_used: bool


def _source_label(packet: SourcePacket, *, index: int) -> str:
    return packet.filename or f"file_{packet.file_id or index + 1}"


def _estimate_text_tokens(text: str) -> int:
    """Estimate token count without mutating the prompt material."""
    if not text.strip():
        return 0
    try:
        from app.shared.infra.llm_support.common import resolve_settings_model
        from app.shared.infra.settings import get_settings

        model, _selector = resolve_settings_model(get_settings(), "reason")
        litellm = load_litellm()
        return len(list(litellm.encode(model=model or "gpt-4o-mini", text=text)))
    except Exception:
        manager = ContextWindowManager()
        return manager.estimate_tokens(text)


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _clean_list(values: list[object] | None, *, limit: int) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = _clean_text(value)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _source_filename_for_section(section: SectionPacket) -> str:
    return section.source_filename or section.source_file_id or "unknown"


def _section_sort_key(section: SectionPacket) -> tuple[str, int]:
    return section.source_file_id, int(section.chunk_index or 0)


def _build_section_batches(
    sections: list[SectionPacket],
) -> list[_MaterialSectionBatch]:
    ordered_sections = sorted(
        [section for section in sections if _clean_text(section.normalized_content)],
        key=_section_sort_key,
    )
    if not ordered_sections:
        return []

    total_chars = sum(max(1, int(section.char_count or len(section.normalized_content or ""))) for section in ordered_sections)
    desired_batches = max(2, ceil(total_chars / _BATCH_TARGET_CHARS))
    desired_batches = min(desired_batches, len(ordered_sections))
    target_chars = max(1, ceil(total_chars / desired_batches))

    raw_batches: list[list[SectionPacket]] = []
    current: list[SectionPacket] = []
    current_chars = 0
    for section in ordered_sections:
        section_chars = max(1, int(section.char_count or len(section.normalized_content or "")))
        if current and len(raw_batches) < desired_batches - 1 and current_chars + section_chars > target_chars:
            raw_batches.append(current)
            current = []
            current_chars = 0
        current.append(section)
        current_chars += section_chars
    if current:
        raw_batches.append(current)

    total_batches = len(raw_batches)
    return [
        _MaterialSectionBatch(batch_index=index + 1, total_batches=total_batches, sections=batch)
        for index, batch in enumerate(raw_batches)
        if batch
    ]


def _cap_text(text: str, max_chars: int) -> str:
    cleaned = str(text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max(1, max_chars - 3)].rstrip() + "..."


def _render_batch_excerpt(batch: _MaterialSectionBatch) -> str:
    sections = list(batch.sections)
    if not sections:
        return ""
    per_section_chars = max(260, min(1400, int(_BATCH_EXCERPT_MAX_CHARS / max(1, len(sections)))))
    blocks: list[str] = []
    used_chars = 0
    for section in sections:
        excerpt = _cap_text(section.normalized_content, per_section_chars)
        if not excerpt:
            continue
        block = "\n".join(
            [
                f"## {section.digest_chunk_uid}",
                f"文件：{_source_filename_for_section(section)}",
                f"标题：{section.title or section.header_path}",
                f"路径：{section.header_path}",
                f"预览：{section.preview}",
                "",
                excerpt,
            ]
        ).strip()
        if used_chars + len(block) > _BATCH_EXCERPT_MAX_CHARS and blocks:
            blocks.append("...[本批次摘录已按预算截断]...")
            break
        blocks.append(block)
        used_chars += len(block)
    return "\n\n".join(blocks).strip()


def _fallback_batch_summary(batch: _MaterialSectionBatch) -> _MaterialBatchSummary:
    titles = _clean_list([section.title or section.header_path for section in batch.sections], limit=10)
    refs = _clean_list([section.digest_chunk_uid for section in batch.sections], limit=8)
    filenames = _clean_list([_source_filename_for_section(section) for section in batch.sections], limit=6)
    return _MaterialBatchSummary(
        summary=f"{'、'.join(filenames) or '本批资料'} 包含 {len(batch.sections)} 个切片，主要围绕：{'、'.join(titles[:6]) or '资料正文'}。",
        topics=titles,
        structure_hints=titles[:6],
        high_value_sections=refs,
        warnings=[],
    )


def _build_batch_summary_messages(batch: _MaterialSectionBatch, excerpt: str) -> list[dict[str, str]]:
    system_prompt = "你是 AITeachMe 的资料理解助手。你只输出合法 JSON，不能编造资料里没有的信息。"
    user_prompt = f"""
请阅读这一批上传资料切片，为 Planner 生成课程方案提供短摘要。

批次：{batch.batch_index}/{batch.total_batches}
切片数量：{len(batch.sections)}

切片内容：
{excerpt}

请输出 JSON：
{{
  "summary": "这一批资料的核心内容，120 字以内",
  "topics": ["关键主题，最多 10 项"],
  "structure_hints": ["可能适合作为章节或小节的结构线索，最多 8 项"],
  "high_value_sections": ["最值得后续 DocGen 深读的 section_ref，最多 8 项"],
  "warnings": ["资料噪声、重复、缺页、OCR 风险等，最多 4 项"]
}}

要求：
1. 只能基于本批切片内容总结。
2. `high_value_sections` 必须来自本批出现的 section_ref。
3. 输出要短，给规划阶段看资料边界，不要写教学正文。
""".strip()
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


async def _summarize_material_batch(batch: _MaterialSectionBatch) -> _MaterialBatchSummary:
    excerpt = _render_batch_excerpt(batch)
    if not excerpt:
        return _fallback_batch_summary(batch)
    try:
        llm_kwargs = planner_completion_kwargs_with_metadata(
            PlannerModelStep.MATERIAL_BATCH_SUMMARY,
            section_batch_index=batch.batch_index,
            section_batch_total=batch.total_batches,
            section_count=len(batch.sections),
        )
        response = await acompletion_with_fallback(
            _build_batch_summary_messages(batch, excerpt),
            response_model=_MaterialBatchSummary,
            **llm_kwargs,
        )
    except Exception as exc:
        logger.warning(
            "planner_material_digest_batch_summary_failed",
            batch_index=batch.batch_index,
            total_batches=batch.total_batches,
            error=str(exc),
        )
        return _fallback_batch_summary(batch)
    try:
        return response if isinstance(response, _MaterialBatchSummary) else _MaterialBatchSummary.model_validate(response)
    except Exception:
        return _fallback_batch_summary(batch)


def _merge_batch_summaries(
    material_context: DigestMaterialContext,
    *,
    summaries: list[_MaterialBatchSummary],
    total_chars: int,
    total_tokens: int,
) -> str:
    profile = material_context.learning_domain_profile
    stats = material_context.material_stats_profile.stats
    topics = _clean_list([topic for summary in summaries for topic in summary.topics], limit=24)
    structure_hints = _clean_list(
        [hint for summary in summaries for hint in summary.structure_hints],
        limit=20,
    )
    high_value_sections = _clean_list(
        [ref for summary in summaries for ref in summary.high_value_sections],
        limit=24,
    )
    warnings = _clean_list([warning for summary in summaries for warning in summary.warnings], limit=8)

    lines = [
        "===== 上传资料并行切片摘要 =====",
        f"资料规模：{len(material_context.source_documents)} 个文件，{len(material_context.material_sections)} 个切片，约 {total_chars} 字 / {total_tokens} tokens。",
    ]
    profile_text = profile.build_context_string().strip() if profile is not None else ""
    if profile_text:
        lines.extend(["", "课程画像：", profile_text])
    if topics:
        lines.extend(["", "高频主题：", "、".join(topics)])
    if structure_hints:
        lines.extend(["", "可能的章节结构线索：", "；".join(structure_hints)])
    if high_value_sections:
        lines.extend(["", "后续值得深读的 section_ref：", "、".join(high_value_sections)])
    if warnings:
        lines.extend(["", "资料风险提示：", "；".join(warnings)])
    if stats.image_count or stats.formula_count or stats.exercise_count:
        lines.extend(
            [
                "",
                "材料信号："
                f"公式 {stats.formula_count}，题目/练习 {stats.exercise_count}，图片 {stats.image_count}。",
            ]
        )

    lines.append("")
    lines.append("分批摘要：")
    for index, summary in enumerate(summaries, start=1):
        batch_lines = [f"{index}. {_cap_text(summary.summary, 260)}"]
        if summary.topics:
            batch_lines.append(f"   主题：{'、'.join(summary.topics[:8])}")
        if summary.high_value_sections:
            batch_lines.append(f"   关键切片：{'、'.join(summary.high_value_sections[:8])}")
        lines.append("\n".join(batch_lines).rstrip())
    return "\n".join(line for line in lines if line is not None).strip()


async def build_material_digest(
    material_context: DigestMaterialContext,
) -> MaterialDigestResult:
    """Return planner-ready material context.

    短资料保持全文上下文；长资料走 section-batch map-reduce，避免把整本
    教材直接塞进 Planner prompt。
    """

    packets = [
        packet
        for packet in list(material_context.source_documents)
        if (packet.normalized_content or "").strip()
    ]
    if not packets:
        return MaterialDigestResult(
            digest="",
            total_chars=0,
            total_tokens=0,
            source_count=0,
            llm_used=False,
        )

    packet_infos = [
        (
            packet,
            len((packet.normalized_content or "").strip()),
            _estimate_text_tokens((packet.normalized_content or "").strip()),
        )
        for packet in packets
    ]
    total_chars = sum(chars for _packet, chars, _tokens in packet_infos)
    total_tokens = sum(tokens for _packet, _chars, tokens in packet_infos)
    if (
        total_chars > _FULL_CONTEXT_MAX_CHARS
        or total_tokens > _FULL_CONTEXT_MAX_TOKENS
    ) and material_context.material_sections:
        batches = _build_section_batches(list(material_context.material_sections))
        if batches:
            summaries = await run_llm_tasks(
                batches,
                _summarize_material_batch,
            )
            return MaterialDigestResult(
                digest=_merge_batch_summaries(
                    material_context,
                    summaries=summaries,
                    total_chars=total_chars,
                    total_tokens=total_tokens,
                ),
                total_chars=total_chars,
                total_tokens=total_tokens,
                source_count=len(packets),
                llm_used=True,
            )
    sections = [
        (
            f"===== 资料 {index + 1}/{len(packets)}：{_source_label(packet, index=index)} =====\n"
            f"本资料约 {token_count} tokens，已完整拼接。\n"
            f"{(packet.normalized_content or '').strip()}"
        ).strip()
        for index, (packet, _chars, token_count) in enumerate(packet_infos)
    ]
    return MaterialDigestResult(
        digest="\n\n".join(sections),
        total_chars=total_chars,
        total_tokens=total_tokens,
        source_count=len(packets),
        llm_used=False,
    )


__all__ = [
    "MaterialDigestResult",
    "build_material_digest",
]
