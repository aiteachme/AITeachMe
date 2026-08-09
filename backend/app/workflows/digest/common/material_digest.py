"""Build bounded planner material context from uploaded material."""

from __future__ import annotations

from dataclasses import dataclass

from app.shared.infra.llm_support.context_window import ContextWindowManager
from app.shared.infra.llm_support.litellm_loader import load_litellm
from app.workflows.digest.common.models import DigestMaterialContext, SectionPacket, SourcePacket

_FULL_CONTEXT_MAX_CHARS = 72_000
_FULL_CONTEXT_MAX_TOKENS = 28_000
_DETERMINISTIC_DIGEST_MAX_CHARS = 56_000
_DETERMINISTIC_MAX_SECTIONS = 36


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


def _clean_list(values: list[object] | None, *, limit: int) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value or "").strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _cap_text(text: object, max_chars: int) -> str:
    cleaned = str(text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max(1, max_chars - 3)].rstrip() + "..."


def _even_positions(count: int, limit: int) -> list[int]:
    if count <= 0 or limit <= 0:
        return []
    if count <= limit:
        return list(range(count))
    if limit == 1:
        return [0]
    return sorted(
        {
            round(offset * (count - 1) / (limit - 1))
            for offset in range(limit)
        }
    )


def _sample_sections(
    sections: list[SectionPacket],
    *,
    limit: int = _DETERMINISTIC_MAX_SECTIONS,
) -> list[SectionPacket]:
    """Sample evenly while retaining each source file's first and last section."""

    ordered = sorted(
        [
            section
            for section in sections
            if str(section.normalized_content or "").strip()
        ],
        key=lambda item: (item.source_file_id, int(item.chunk_index or 0)),
    )
    if len(ordered) <= limit:
        return ordered

    positions_by_file: dict[str, list[int]] = {}
    for position, section in enumerate(ordered):
        positions_by_file.setdefault(section.source_file_id, []).append(position)
    boundary_positions = sorted(
        {
            boundary
            for positions in positions_by_file.values()
            for boundary in (positions[0], positions[-1])
        }
    )
    if len(boundary_positions) >= limit:
        chosen = {
            boundary_positions[position]
            for position in _even_positions(len(boundary_positions), limit)
        }
    else:
        chosen = set(boundary_positions)
        remaining = [
            position
            for position in range(len(ordered))
            if position not in chosen
        ]
        for offset in _even_positions(len(remaining), limit - len(chosen)):
            chosen.add(remaining[offset])
    return [ordered[position] for position in sorted(chosen)]


def _render_section(section: SectionPacket, *, excerpt_chars: int) -> str:
    title = section.title or section.header_path or f"Part {section.chunk_index + 1}"
    return "\n".join(
        [
            f"### {section.digest_chunk_uid}",
            f"文件：{section.source_filename or section.source_file_id or 'unknown'}",
            f"标题：{title}",
            f"路径：{section.header_path}",
            "",
            _cap_text(section.normalized_content, excerpt_chars),
        ]
    ).strip()


def _build_deterministic_long_digest(
    material_context: DigestMaterialContext,
    *,
    total_chars: int,
    total_tokens: int,
) -> str:
    """Pack representative parsed sections without another model call."""

    profile = material_context.learning_domain_profile
    hints = material_context.material_hints
    stats = material_context.material_stats_profile.stats
    selected_sections = _sample_sections(list(material_context.material_sections))
    excerpt_chars = max(
        320,
        min(
            1_200,
            int(
                (_DETERMINISTIC_DIGEST_MAX_CHARS - 10_000)
                / max(1, len(selected_sections))
            )
            - 180,
        ),
    )
    lines = [
        "===== 上传资料结构化摘录 =====",
        (
            f"资料规模：{len(material_context.source_documents)} 个文件，"
            f"{len(material_context.material_sections)} 个切片，约 {total_chars} 字 / {total_tokens} tokens。"
        ),
        (
            f"说明：以下按文件边界和全文位置确定性选取 {len(selected_sections)} 个切片，"
            "保留 section_ref，未经过额外模型改写。"
        ),
    ]
    profile_text = profile.build_context_string().strip()
    if profile_text and profile_text != "（未识别课程）":
        lines.extend(["", "课程画像：", profile_text])
    chapter_candidates = _clean_list(list(hints.chapter_candidates), limit=24)
    high_freq_terms = _clean_list([item[0] for item in hints.high_freq_terms], limit=30)
    if chapter_candidates:
        lines.extend(["", "目录线索：", "、".join(chapter_candidates)])
    if high_freq_terms:
        lines.extend(["", "高频主题：", "、".join(high_freq_terms)])
    if stats.formula_count or stats.exercise_count or stats.image_count:
        lines.extend(
            [
                "",
                (
                    f"材料信号：公式 {stats.formula_count}，"
                    f"题目/练习 {stats.exercise_count}，图片 {stats.image_count}。"
                ),
            ]
        )

    section_blocks = [
        _render_section(section, excerpt_chars=excerpt_chars)
        for section in selected_sections
    ]
    digest = "\n\n".join([*lines, *section_blocks]).strip()
    if len(digest) <= _DETERMINISTIC_DIGEST_MAX_CHARS:
        return digest

    tail = section_blocks[-1] if section_blocks else ""
    marker_text = "\n\n...[中间摘录已按 Planner 上下文预算压缩]...\n\n"
    prefix_budget = max(
        1,
        _DETERMINISTIC_DIGEST_MAX_CHARS - len(marker_text) - len(tail),
    )
    prefix = _cap_text("\n\n".join([*lines, *section_blocks[:-1]]), prefix_budget)
    return f"{prefix}{marker_text}{tail}".strip()


async def build_material_digest(
    material_context: DigestMaterialContext,
) -> MaterialDigestResult:
    """Return full short material or a bounded deterministic long-material digest."""

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
        return MaterialDigestResult(
            digest=_build_deterministic_long_digest(
                material_context,
                total_chars=total_chars,
                total_tokens=total_tokens,
            ),
            total_chars=total_chars,
            total_tokens=total_tokens,
            source_count=len(packets),
            llm_used=False,
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
