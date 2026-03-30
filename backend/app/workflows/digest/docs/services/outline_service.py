"""Pure helpers for outline planning in the docs lane."""

from __future__ import annotations

from collections import defaultdict
import json
import re
from pathlib import Path

import structlog

from app.infra.llm import acompletion
from app.infra.model_router import TaskType
from app.workflows.digest.kg.services.chunker import chunk_markdown
from app.workflows.digest.prompts.docgen_prompts import (
    GLOBAL_OUTLINE_PROMPT,
    LOCAL_OUTLINE_PROMPT,
)
from app.workflows.digest.shared.models import FastTopicHints, SectionPacket
from app.workflows.digest.unified.models import TopicAnchorSnapshot

logger = structlog.get_logger()

_MARKDOWN_HEADER_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", re.MULTILINE)
_NUMBERED_HEADING_PATTERN = re.compile(
    r"^\s*(?:第[一二三四五六七八九十百千万0-9]+[章节讲部分]|[0-9]+(?:\.[0-9]+){0,2}|[一二三四五六七八九十]+)[、.．\s:：-]+(.+?)\s*$",
    re.MULTILINE,
)
_NUMBER_PREFIX_PATTERN = re.compile(
    r"^\s*(?:第[一二三四五六七八九十百千万0-9]+[章节讲部分]|[0-9]+(?:\.[0-9]+){0,2}|[一二三四五六七八九十]+)[、.．\s:：-]+"
)
_LATEX_BLOCK_PATTERN = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
_LATEX_INLINE_PATTERN = re.compile(r"\$([^$\n]{2,160})\$")
_SPACE_PATTERN = re.compile(r"\s+")
_HEADER_PATH_SPLIT_PATTERN = re.compile(r"\s*>\s*")
_PUNCT_ONLY_PATTERN = re.compile(r"^[\W_]+$")
_FORMULA_HINTS = (
    "=",
    "lim",
    "sin",
    "cos",
    "tan",
    "ln",
    "log",
    "f(x)",
    "P(",
    "E(",
    "Var(",
)
_QUESTION_TITLE_PATTERN = re.compile(
    r"^(?:question\s*\d+|q\s*\d+|第\s*\d+\s*题|\d+\s*[.)、．])",
    re.IGNORECASE,
)
_PROCEDURAL_HINTS = (
    "考试",
    "试卷",
    "答题",
    "注意",
    "须知",
    "说明",
    "时间",
    "满分",
    "考生",
    "作答",
    "规则",
    "分值",
    "page ocr",
    "fallback",
    "page",
    "ocr",
    "preamble",
    "准考证号",
    "答题纸",
    "条形码",
    "代表正确选项",
    "小方格涂黑",
    "一个正确选项",
    "只有一个正确",
    "不得错位",
)
_GENERIC_OUTLINE_TITLES = {
    "page ocr",
    "preamble",
    "未分类内容",
    "page",
    "ocr",
}
_APPENDIX_CHAPTER_TITLE = "试卷说明与作答规则"
_OVERFLOW_CHAPTER_TITLE = "典型题与综合应用"
_PRIMARY_ANCHOR_NODE_TYPES = {"Topic", "Concept", "Method"}


def _split_content_batches(content: str, batch_count: int) -> list[str]:
    digest_chunks = [chunk.content.strip() for chunk in chunk_markdown(content) if chunk.content.strip()]
    if batch_count <= 1:
        return [content]
    if len(digest_chunks) <= 1:
        digest_chunks = [paragraph.strip() for paragraph in content.split("\n\n") if paragraph.strip()]
    if len(digest_chunks) <= 1:
        return [content]

    bucket_count = min(batch_count, len(digest_chunks))
    base_size, remainder = divmod(len(digest_chunks), bucket_count)
    batches: list[str] = []
    cursor = 0
    for bucket_index in range(bucket_count):
        take = base_size + (1 if bucket_index < remainder else 0)
        batch_chunks = digest_chunks[cursor: cursor + take]
        cursor += take
        if batch_chunks:
            batches.append("\n\n".join(batch_chunks).strip())
    return batches or [content]


def _partition_items(items: list[str], bucket_count: int) -> list[list[str]]:
    if not items:
        return []

    normalized_bucket_count = max(1, min(bucket_count, len(items)))
    base_size, remainder = divmod(len(items), normalized_bucket_count)
    groups: list[list[str]] = []
    cursor = 0
    for bucket_index in range(normalized_bucket_count):
        take = base_size + (1 if bucket_index < remainder else 0)
        group = items[cursor: cursor + take]
        cursor += take
        if group:
            groups.append(group)
    return groups


def _clean_title(title: str) -> str:
    normalized = title.strip().strip("-").strip(":").strip("：").strip()
    normalized = _SPACE_PATTERN.sub(" ", normalized)
    return normalized[:40]


def _dedupe_titles(titles: list[str], *, limit: int = 8) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for raw in titles:
        title = _clean_title(raw)
        if (
            not title
            or len(title) < 2
            or len(title) > 40
            or _PUNCT_ONLY_PATTERN.match(title)
            or title in seen
        ):
            continue
        seen.add(title)
        deduped.append(title)
        if len(deduped) >= limit:
            break
    return deduped


def _dedupe_formula_refs(formulas: list[str], *, limit: int = 10) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for raw in formulas:
        normalized = _SPACE_PATTERN.sub(" ", raw).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
        if len(deduped) >= limit:
            break
    return deduped


def _looks_like_question_title(title: str) -> bool:
    return bool(_QUESTION_TITLE_PATTERN.match(title.strip()))


def _is_procedural_text(text: str) -> bool:
    lowered = text.lower()
    return any(hint in lowered for hint in _PROCEDURAL_HINTS)


def _strip_title_prefix(title: str) -> str:
    cleaned = _clean_title(title)
    return _SPACE_PATTERN.sub(" ", _NUMBER_PREFIX_PATTERN.sub("", cleaned)).strip()


def _header_path_segments(packet: SectionPacket) -> list[str]:
    segments = [
        _strip_title_prefix(segment)
        for segment in _HEADER_PATH_SPLIT_PATTERN.split(packet.header_path)
        if segment.strip()
    ]
    return [
        segment
        for segment in segments
        if segment and segment.lower() not in _GENERIC_OUTLINE_TITLES
    ]


def _is_generic_title(title: str) -> bool:
    cleaned = _strip_title_prefix(title)
    if not cleaned:
        return True
    if cleaned.lower() in _GENERIC_OUTLINE_TITLES:
        return True
    if _is_procedural_text(cleaned):
        return True
    if _looks_like_question_title(cleaned):
        return True
    return len(cleaned) < 2 or _PUNCT_ONLY_PATTERN.match(cleaned) is not None


def _is_procedural_packet(packet: SectionPacket) -> bool:
    if _looks_like_question_title(packet.title) or _QUESTION_TITLE_PATTERN.search(packet.header_path):
        return False
    if packet.question_block_count >= 2 or packet.formula_refs:
        return False

    title_text = f"{packet.title} {packet.header_path}"
    if _is_procedural_text(title_text):
        return packet.char_count <= 600
    if packet.question_block_count == 0 and packet.char_count < 220 and _is_generic_title(packet.title):
        return True
    if not packet.preview.strip():
        return True
    if "page ocr" in packet.title.lower() and packet.char_count < 180:
        return True
    return False


def _derive_theme_title(packet: SectionPacket) -> str:
    if _is_procedural_packet(packet):
        return _APPENDIX_CHAPTER_TITLE
    cleaned_title = _strip_title_prefix(packet.title)
    if packet.question_block_count > 0 or _looks_like_question_title(cleaned_title):
        return _OVERFLOW_CHAPTER_TITLE

    for segment in reversed(_header_path_segments(packet)):
        if not _is_generic_title(segment):
            return segment
    if cleaned_title and not _is_generic_title(cleaned_title):
        return cleaned_title
    return "核心知识梳理"


def _select_outline_section_title(packet: SectionPacket, *, chapter_title: str) -> str:
    cleaned_title = _strip_title_prefix(packet.title)
    if cleaned_title and cleaned_title != chapter_title and cleaned_title.lower() not in _GENERIC_OUTLINE_TITLES:
        return cleaned_title

    for segment in reversed(_header_path_segments(packet)):
        if segment != chapter_title and segment.lower() not in _GENERIC_OUTLINE_TITLES:
            return segment

    if packet.question_block_count > 0 or _looks_like_question_title(packet.title):
        return "典型题目"
    if _is_procedural_packet(packet):
        return "考试要求"
    return chapter_title if chapter_title != _OVERFLOW_CHAPTER_TITLE else "核心材料"


def _build_outline_section(packet: SectionPacket, *, chapter_title: str) -> dict:
    return {
        "title": _select_outline_section_title(packet, chapter_title=chapter_title),
        "source_chunk_indices": [],
        "chunk_uids": [packet.digest_chunk_uid],
        "source_file_ids": [packet.source_file_id],
    }


def _renumber_outline_tree(outline_tree: dict) -> dict:
    chapters = outline_tree.get("chapters", [])
    for index, chapter in enumerate(chapters, start=1):
        chapter["chapter_index"] = index
    return outline_tree


def build_thematic_outline_tree(
    section_packets: list[SectionPacket],
    *,
    fast_hints: FastTopicHints | None = None,
    max_chapters: int = 8,
) -> dict:
    """Build a simple structure-first fallback outline from canonical sections."""

    del fast_hints

    if not section_packets:
        return {"chapters": []}

    grouped_packets: dict[str, list[SectionPacket]] = defaultdict(list)
    chapter_order: list[str] = []

    for packet in section_packets:
        chapter_title = _derive_theme_title(packet)
        if chapter_title not in grouped_packets:
            chapter_order.append(chapter_title)
        grouped_packets[chapter_title].append(packet)

    chapters: list[dict] = []
    for chapter_title in chapter_order[:max_chapters]:
        packets = grouped_packets[chapter_title]
        chapters.append(
            {
                "chapter_index": len(chapters) + 1,
                "title": chapter_title,
                "chunk_uids": [packet.digest_chunk_uid for packet in packets],
                "sections": [
                    _build_outline_section(packet, chapter_title=chapter_title)
                    for packet in packets
                ],
            }
        )

    overflow_titles = chapter_order[max_chapters:]
    if overflow_titles:
        overflow_packets = [
            packet
            for chapter_title in overflow_titles
            for packet in grouped_packets[chapter_title]
        ]
        chapters.append(
            {
                "chapter_index": len(chapters) + 1,
                "title": _OVERFLOW_CHAPTER_TITLE,
                "chunk_uids": [packet.digest_chunk_uid for packet in overflow_packets],
                "sections": [
                    _build_outline_section(packet, chapter_title=_OVERFLOW_CHAPTER_TITLE)
                    for packet in overflow_packets
                ],
            }
        )

    return _renumber_outline_tree({"chapters": chapters})


def build_thematic_outline_summary(outline_tree: dict) -> str:
    """Render a human-readable summary of the deterministic theme plan."""

    lines: list[str] = []
    for chapter in outline_tree.get("chapters", []):
        lines.append(f"Theme chapter {chapter.get('chapter_index', '?')}: {chapter.get('title', '')}")
        for section in chapter.get("sections", []):
            lines.append(f"  - {section.get('title', '')}")
    return "\n".join(lines)


def _anchor_type_priority(node_type: str) -> int:
    if node_type == "Topic":
        return 3
    if node_type == "Method":
        return 2
    if node_type == "Concept":
        return 1
    return 0


def _anchor_sort_key(anchor: tuple[str, str, float]) -> tuple[float, float, str]:
    topic_name, node_type, confidence = anchor
    return (-_anchor_type_priority(node_type), -confidence, topic_name)


def _collect_anchor_support(
    section_packets: list[SectionPacket],
    *,
    topic_snapshot: TopicAnchorSnapshot,
) -> tuple[dict[str, list[tuple[str, str, float]]], dict[str, dict]]:
    packets_by_uid = {
        packet.digest_chunk_uid: packet
        for packet in section_packets
    }
    anchors_by_chunk_uid: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
    support_by_topic: dict[str, dict] = {}

    for anchor in topic_snapshot.anchors:
        cleaned_name = _clean_title(anchor.topic_name)
        if not cleaned_name or _is_generic_title(cleaned_name) or anchor.confidence < 0.55:
            continue

        valid_chunk_uids = [
            chunk_uid
            for chunk_uid in dict.fromkeys(anchor.chunk_uids)
            if chunk_uid in packets_by_uid
        ]
        if not valid_chunk_uids:
            continue

        support = support_by_topic.setdefault(
            cleaned_name,
            {
                "topic_name": cleaned_name,
                "node_type": anchor.node_type,
                "confidence": anchor.confidence,
                "chunk_uids": [],
            },
        )
        if (
            _anchor_type_priority(anchor.node_type) > _anchor_type_priority(str(support["node_type"]))
            or (
                anchor.node_type == support["node_type"]
                and anchor.confidence > float(support["confidence"])
            )
        ):
            support["node_type"] = anchor.node_type
            support["confidence"] = anchor.confidence

        support["chunk_uids"] = list(
            dict.fromkeys([*support["chunk_uids"], *valid_chunk_uids])
        )
        for chunk_uid in valid_chunk_uids:
            anchors_by_chunk_uid[chunk_uid].append(
                (cleaned_name, anchor.node_type, anchor.confidence)
            )

    deduped_anchors_by_chunk_uid: dict[str, list[tuple[str, str, float]]] = {}
    for chunk_uid, anchors in anchors_by_chunk_uid.items():
        deduped = list(
            dict.fromkeys(
                (
                    topic_name,
                    node_type,
                    round(confidence, 4),
                )
                for topic_name, node_type, confidence in anchors
            )
        )
        deduped_anchors_by_chunk_uid[chunk_uid] = sorted(deduped, key=_anchor_sort_key)
    return deduped_anchors_by_chunk_uid, support_by_topic


def _semantic_seed_score(anchor_support: dict, packets_by_uid: dict[str, SectionPacket]) -> float:
    chunk_uids = [
        chunk_uid
        for chunk_uid in anchor_support["chunk_uids"]
        if chunk_uid in packets_by_uid
    ]
    if not chunk_uids:
        return -1.0

    non_procedural_count = sum(
        1
        for chunk_uid in chunk_uids
        if not _is_procedural_packet(packets_by_uid[chunk_uid])
    )
    return (
        non_procedural_count * 3.0
        + len(chunk_uids) * 1.5
        + float(anchor_support["confidence"]) * 2.0
        + _anchor_type_priority(str(anchor_support["node_type"])) * 1.2
    )


def _select_semantic_seed_titles(
    section_packets: list[SectionPacket],
    *,
    anchors_by_chunk_uid: dict[str, list[tuple[str, str, float]]],
    support_by_topic: dict[str, dict],
    max_chapters: int,
) -> list[str]:
    packets_by_uid = {
        packet.digest_chunk_uid: packet
        for packet in section_packets
    }
    ranked_support = sorted(
        support_by_topic.values(),
        key=lambda item: (
            -_semantic_seed_score(item, packets_by_uid),
            item["topic_name"],
        ),
    )

    selected_titles: list[str] = []
    covered_chunk_uids: set[str] = set()
    for anchor_support in ranked_support:
        chunk_uids = [
            chunk_uid
            for chunk_uid in anchor_support["chunk_uids"]
            if chunk_uid in packets_by_uid
        ]
        uncovered_semantic_chunks = [
            chunk_uid
            for chunk_uid in chunk_uids
            if chunk_uid not in covered_chunk_uids
            and not _is_procedural_packet(packets_by_uid[chunk_uid])
        ]
        if not uncovered_semantic_chunks and selected_titles:
            continue

        topic_name = str(anchor_support["topic_name"])
        selected_titles.append(topic_name)
        covered_chunk_uids.update(uncovered_semantic_chunks or chunk_uids)
        if len(selected_titles) >= max_chapters:
            break

    if len(selected_titles) >= max_chapters:
        return selected_titles

    for packet in section_packets:
        if _is_procedural_packet(packet):
            continue
        if packet.digest_chunk_uid in covered_chunk_uids:
            continue
        packet_anchors = anchors_by_chunk_uid.get(packet.digest_chunk_uid, [])
        if not packet_anchors:
            continue

        fallback_topic_name = packet_anchors[0][0]
        if fallback_topic_name not in selected_titles:
            selected_titles.append(fallback_topic_name)
        covered_chunk_uids.add(packet.digest_chunk_uid)
        if len(selected_titles) >= max_chapters:
            break
    return selected_titles


def _select_semantic_section_title(
    packet: SectionPacket,
    *,
    packet_anchors: list[tuple[str, str, float]],
    chapter_title: str,
) -> str:
    cleaned_title = _strip_title_prefix(packet.title)
    if cleaned_title and not _is_generic_title(cleaned_title) and cleaned_title != chapter_title:
        return cleaned_title

    subordinate_anchor_names = list(
        dict.fromkeys(
            topic_name
            for topic_name, node_type, _ in packet_anchors
            if topic_name != chapter_title
            and topic_name.strip()
            and not _is_generic_title(topic_name)
            and node_type in {"Concept", "Method", "Definition", "Example"}
        )
    )
    if subordinate_anchor_names:
        return "、".join(subordinate_anchor_names[:2])

    for segment in reversed(_header_path_segments(packet)):
        if segment != chapter_title and not _is_generic_title(segment):
            return segment

    if cleaned_title and cleaned_title != chapter_title:
        return cleaned_title
    return _select_outline_section_title(packet, chapter_title=chapter_title)


def build_anchor_outline_tree(
    section_packets: list[SectionPacket],
    *,
    topic_snapshot: TopicAnchorSnapshot | None,
    max_chapters: int = 8,
) -> dict:
    """Build a semantic outline directly from graph topic anchors."""

    if topic_snapshot is None or not topic_snapshot.anchors or not section_packets:
        return {"chapters": []}

    anchors_by_chunk_uid, support_by_topic = _collect_anchor_support(
        section_packets,
        topic_snapshot=topic_snapshot,
    )
    if not support_by_topic:
        return {"chapters": []}

    seed_titles = _select_semantic_seed_titles(
        section_packets,
        anchors_by_chunk_uid=anchors_by_chunk_uid,
        support_by_topic=support_by_topic,
        max_chapters=max_chapters,
    )
    grouped_packets: dict[str, list[tuple[SectionPacket, str]]] = defaultdict(list)
    chapter_order: list[str] = []

    for packet in section_packets:
        anchor_candidates = anchors_by_chunk_uid.get(packet.digest_chunk_uid, [])
        matching_seed_titles = [
            topic_name
            for topic_name, _, _ in anchor_candidates
            if topic_name in seed_titles
        ]
        chapter_title = (
            matching_seed_titles[0]
            if matching_seed_titles
            else anchor_candidates[0][0]
            if anchor_candidates
            else _derive_theme_title(packet)
        )
        if _is_procedural_packet(packet) and not anchor_candidates:
            chapter_title = _APPENDIX_CHAPTER_TITLE

        section_title = _select_semantic_section_title(
            packet,
            packet_anchors=anchor_candidates,
            chapter_title=chapter_title,
        )
        if chapter_title not in grouped_packets:
            chapter_order.append(chapter_title)
        grouped_packets[chapter_title].append((packet, section_title))

    chapters: list[dict] = []
    for chapter_title in chapter_order[:max_chapters]:
        chapter_entries = grouped_packets[chapter_title]
        chapters.append(
            {
                "chapter_index": len(chapters) + 1,
                "title": chapter_title,
                "chunk_uids": [packet.digest_chunk_uid for packet, _ in chapter_entries],
                "sections": [
                    {
                        "title": section_title,
                        "source_chunk_indices": [],
                        "chunk_uids": [packet.digest_chunk_uid],
                        "source_file_ids": [packet.source_file_id],
                    }
                    for packet, section_title in chapter_entries
                ],
            }
        )

    overflow_titles = chapter_order[max_chapters:]
    if overflow_titles:
        overflow_entries = [
            entry
            for chapter_title in overflow_titles
            for entry in grouped_packets[chapter_title]
        ]
        chapters.append(
            {
                "chapter_index": len(chapters) + 1,
                "title": _OVERFLOW_CHAPTER_TITLE,
                "chunk_uids": [packet.digest_chunk_uid for packet, _ in overflow_entries],
                "sections": [
                    {
                        "title": section_title,
                        "source_chunk_indices": [],
                        "chunk_uids": [packet.digest_chunk_uid],
                        "source_file_ids": [packet.source_file_id],
                    }
                    for packet, section_title in overflow_entries
                ],
            }
        )

    return _renumber_outline_tree({"chapters": chapters})


def extract_headers(content: str) -> list[str]:
    """Extract headings from markdown or numbered lines."""

    markdown_headers = _MARKDOWN_HEADER_PATTERN.findall(content)
    numbered_headers = _NUMBERED_HEADING_PATTERN.findall(content)
    return _dedupe_titles([*markdown_headers, *numbered_headers], limit=12)


def infer_outline_candidates(content: str, *, source_filename: str) -> list[str]:
    """Infer lightweight section candidates without extra LLM calls."""

    headers = extract_headers(content)
    if headers:
        return headers

    short_lines: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if len(stripped) <= 28 and stripped.count(" ") <= 4 and "。" not in stripped:
            short_lines.append(stripped)
        if len(short_lines) >= 6:
            break

    fallback = Path(source_filename).stem.replace("_", " ").replace("-", " ").strip() or "未命名主题"
    return _dedupe_titles([*short_lines, fallback], limit=6) or [fallback]


def build_chunk_preview(content: str, *, max_chars: int = 240) -> str:
    """Build a short preview string for outline planning."""

    parts: list[str] = []
    for line in content.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if len(stripped) < 2:
            continue
        parts.append(stripped)
        joined = " ".join(parts)
        if len(joined) >= max_chars:
            return joined[:max_chars].rstrip()
    return " ".join(parts)[:max_chars].rstrip()


def extract_formula_candidates(content: str, *, limit: int = 8) -> list[str]:
    """Extract formula cues for chapter drafting and review."""

    formulas: list[str] = []
    for block in _LATEX_BLOCK_PATTERN.findall(content):
        normalized = block.strip()
        if normalized:
            formulas.append(f"$${normalized}$$")

    for inline in _LATEX_INLINE_PATTERN.findall(content):
        normalized = inline.strip()
        if normalized:
            formulas.append(f"${normalized}$")

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or len(stripped) > 120:
            continue
        if any(hint in stripped for hint in _FORMULA_HINTS) and len(re.findall(r"[A-Za-z0-9]", stripped)) >= 2:
            formulas.append(stripped)

    return _dedupe_formula_refs(formulas, limit=limit)


def _estimate_single_chunk_chapter_count(content: str, titles: list[str]) -> int:
    title_count = len(titles)
    content_length = len(content.strip())
    if title_count >= 8:
        return 4
    if title_count >= 5:
        return 3
    if title_count >= 2:
        return 2
    if content_length >= 6000:
        return 4
    if content_length >= 3200:
        return 3
    if content_length >= 900:
        return 2
    return 1


def _build_outline_sections(titles: list[str], *, source_chunk_index: int) -> list[dict]:
    section_titles = _dedupe_titles(titles, limit=4) or ["核心内容"]
    return [
        {
            "title": title,
            "source_chunk_indices": [source_chunk_index],
        }
        for title in section_titles
    ]


def _build_single_chunk_outline(chunk: dict, local_outline: dict | None) -> dict:
    source_filename = str(chunk.get("source_filename", "未命名主题"))
    content = str(chunk.get("content", ""))
    local_titles = _dedupe_titles(list((local_outline or {}).get("titles", [])), limit=12)
    desired_chapter_count = _estimate_single_chunk_chapter_count(content, local_titles)

    if desired_chapter_count <= 1:
        chapter_title = (
            local_titles[0]
            if local_titles
            else infer_outline_candidates(content, source_filename=source_filename)[0]
        )
        section_titles = local_titles[1:4] or infer_outline_candidates(
            content,
            source_filename=source_filename,
        )[1:4]
        return {
            "chapters": [
                {
                    "chapter_index": 1,
                    "title": chapter_title,
                    "sections": _build_outline_sections(section_titles, source_chunk_index=0),
                }
            ]
        }

    content_batches = _split_content_batches(content, desired_chapter_count)
    grouped_titles = _partition_items(local_titles, len(content_batches))
    chapters: list[dict] = []
    for chapter_index, batch in enumerate(content_batches, start=1):
        title_group = grouped_titles[chapter_index - 1] if chapter_index - 1 < len(grouped_titles) else []
        batch_titles = infer_outline_candidates(batch, source_filename=source_filename)
        chapter_title = (
            title_group[0]
            if title_group
            else batch_titles[0]
            if batch_titles
            else f"{Path(source_filename).stem or '知识主题'} 第{chapter_index}部分"
        )
        section_titles = title_group[1:] or batch_titles[1:4]
        chapters.append(
            {
                "chapter_index": chapter_index,
                "title": chapter_title,
                "sections": _build_outline_sections(section_titles, source_chunk_index=0),
            }
        )
    return {"chapters": chapters}


def build_fallback_outline_tree(clean_chunks: list[dict], local_outlines: list[dict]) -> dict:
    """Build a deterministic fallback outline tree."""

    if not clean_chunks:
        return {"chapters": []}

    if len(clean_chunks) == 1:
        local_outline = local_outlines[0] if local_outlines else {}
        return _build_single_chunk_outline(clean_chunks[0], local_outline)

    chapters: list[dict] = []
    for index, chunk in enumerate(clean_chunks):
        local_outline = local_outlines[index] if index < len(local_outlines) else {}
        local_titles = _dedupe_titles(list(local_outline.get("titles", [])), limit=8)
        inferred_titles = infer_outline_candidates(
            str(chunk.get("content", "")),
            source_filename=str(chunk.get("source_filename", f"chunk_{index}")),
        )
        titles = local_titles or inferred_titles
        chapter_title = titles[0] if titles else f"第{index + 1}章"
        section_titles = titles[1:4] or inferred_titles[1:4]
        chapters.append(
            {
                "chapter_index": index + 1,
                "title": chapter_title,
                "sections": _build_outline_sections(section_titles, source_chunk_index=index),
            }
        )
    return {"chapters": chapters}


def ensure_multi_chapter_outline(
    outline_tree: dict,
    clean_chunks: list[dict],
    local_outlines: list[dict],
) -> dict:
    """Prevent a large source from collapsing into one weak chapter."""

    chapters = outline_tree.get("chapters", [])
    if not clean_chunks:
        return {"chapters": []}

    fallback_tree = build_fallback_outline_tree(clean_chunks, local_outlines)
    fallback_chapters = fallback_tree.get("chapters", [])
    if not chapters:
        return fallback_tree
    if len(chapters) >= 2:
        return outline_tree
    if len(fallback_chapters) >= 2:
        return fallback_tree
    return outline_tree


def _dedupe_section_packets(section_packets: list[SectionPacket]) -> list[SectionPacket]:
    deduped: list[SectionPacket] = []
    seen: set[str] = set()
    for packet in section_packets:
        if packet.digest_chunk_uid in seen:
            continue
        seen.add(packet.digest_chunk_uid)
        deduped.append(packet)
    return deduped


def _normalize_outline_key(text: str) -> str:
    return re.sub(r"\s+", "", _strip_title_prefix(text).lower())


def _packet_matches_section_title(packet: SectionPacket, section_title: str) -> bool:
    normalized_title = _normalize_outline_key(section_title)
    if not normalized_title:
        return False

    packet_keys = {
        _normalize_outline_key(packet.title),
        *[_normalize_outline_key(segment) for segment in _header_path_segments(packet)],
    }
    return any(
        packet_key and (
            normalized_title == packet_key
            or normalized_title in packet_key
            or packet_key in normalized_title
        )
        for packet_key in packet_keys
    )


def _resolve_packets_for_outline_chapter(
    chapter: dict,
    *,
    clean_chunks: list[dict],
    section_packets: list[SectionPacket],
) -> list[SectionPacket]:
    packets_by_uid = {
        packet.digest_chunk_uid: packet
        for packet in section_packets
    }
    explicit_chunk_uids = [
        str(chunk_uid)
        for chunk_uid in [
            *chapter.get("chunk_uids", []),
            *[
                chunk_uid
                for section in chapter.get("sections", [])
                for chunk_uid in section.get("chunk_uids", [])
            ],
        ]
        if str(chunk_uid).strip()
    ]
    if explicit_chunk_uids:
        return _dedupe_section_packets(
            [
                packets_by_uid[chunk_uid]
                for chunk_uid in explicit_chunk_uids
                if chunk_uid in packets_by_uid
            ]
        )

    source_file_ids = {
        int(clean_chunks[index].get("file_id", 0))
        for section in chapter.get("sections", [])
        for index in section.get("source_chunk_indices", [])
        if 0 <= index < len(clean_chunks)
    }
    filtered_packets = [
        packet
        for packet in section_packets
        if not source_file_ids or packet.source_file_id in source_file_ids
    ]

    section_titles = [
        str(section.get("title", "")).strip()
        for section in chapter.get("sections", [])
        if str(section.get("title", "")).strip()
    ]
    if section_titles:
        exact_matches = [
            packet
            for packet in filtered_packets
            if any(_packet_matches_section_title(packet, section_title) for section_title in section_titles)
        ]
        if exact_matches:
            return _dedupe_section_packets(exact_matches)

    return _dedupe_section_packets(filtered_packets)


def _score_outline_tree(
    outline_tree: dict,
    *,
    clean_chunks: list[dict],
    section_packets: list[SectionPacket],
) -> float:
    chapters = outline_tree.get("chapters", [])
    if not chapters:
        return -1.0

    score = 0.0
    covered_chunk_uids: set[str] = set()
    for chapter_index, chapter in enumerate(chapters):
        packets = _resolve_packets_for_outline_chapter(
            chapter,
            clean_chunks=clean_chunks,
            section_packets=section_packets,
        )
        if not packets:
            score -= 2.0
            continue

        score += len(packets)
        score += len({packet.digest_chunk_uid for packet in packets} - covered_chunk_uids) * 0.5
        covered_chunk_uids.update(packet.digest_chunk_uid for packet in packets)
        if all(_is_procedural_packet(packet) for packet in packets):
            score -= 2.5
            if chapter_index == 0 and len(chapters) > 1:
                score -= 3.0
        else:
            score += 2.0

        chapter_title = str(chapter.get("title", ""))
        if _is_generic_title(chapter_title):
            score -= 1.0
        else:
            score += 0.5
    return score


def select_preferred_outline_tree(
    *,
    llm_outline_tree: dict,
    thematic_outline_tree: dict,
    clean_chunks: list[dict],
    section_packets: list[SectionPacket],
    prefer_thematic_alignment: bool = False,
) -> dict:
    """Choose the outline that better matches non-procedural teaching coverage."""

    llm_score = _score_outline_tree(
        llm_outline_tree,
        clean_chunks=clean_chunks,
        section_packets=section_packets,
    )
    thematic_score = _score_outline_tree(
        thematic_outline_tree,
        clean_chunks=clean_chunks,
        section_packets=section_packets,
    )
    if prefer_thematic_alignment and thematic_outline_tree.get("chapters"):
        if thematic_score >= llm_score - 1.0:
            return thematic_outline_tree
    if thematic_score > llm_score:
        return thematic_outline_tree
    return llm_outline_tree


def build_chapter_assignments_from_sections(
    outline_tree: dict,
    *,
    clean_chunks: list[dict],
    section_packets: list[SectionPacket],
) -> list[dict]:
    """Build chapter assignments directly from canonical section packets."""

    assignments: list[dict] = []
    for chapter in outline_tree.get("chapters", []):
        chapter_packets = _resolve_packets_for_outline_chapter(
            chapter,
            clean_chunks=clean_chunks,
            section_packets=section_packets,
        )
        if not chapter_packets:
            continue

        section_payloads = [
            {
                "section_index": index,
                "title": _clean_title(packet.title) or f"第{index}节",
                "source_contents": [packet.normalized_content],
                "source_file_ids": [packet.source_file_id],
                "chunk_uids": [packet.digest_chunk_uid],
                "preview": packet.preview,
                "header_path": packet.header_path,
                "formula_refs": list(packet.formula_refs),
                "image_refs": list(packet.image_refs),
            }
            for index, packet in enumerate(chapter_packets, start=1)
        ]
        source_contents = [packet.normalized_content for packet in chapter_packets]
        source_file_ids = list(
            dict.fromkeys(packet.source_file_id for packet in chapter_packets)
        )
        source_filenames = list(
            dict.fromkeys(packet.source_filename for packet in chapter_packets)
        )
        formula_refs = _dedupe_formula_refs(
            [
                formula
                for packet in chapter_packets
                for formula in packet.formula_refs
            ],
            limit=10,
        )
        image_refs = list(
            dict.fromkeys(ref for packet in chapter_packets for ref in packet.image_refs)
        )
        brief_lines = [
            f"- {packet.header_path or packet.title}: {packet.preview}"
            for packet in chapter_packets[:8]
        ]

        assignments.append(
            {
                "chapter_index": int(chapter.get("chapter_index", len(assignments) + 1)),
                "title": str(chapter.get("title", f"第{len(assignments) + 1}章")),
                "sections": list(chapter.get("sections", [])),
                "section_titles": [
                    payload["title"]
                    for payload in section_payloads
                    if str(payload.get("title", "")).strip()
                ],
                "section_payloads": section_payloads,
                "source_contents": source_contents,
                "source_file_ids": source_file_ids,
                "source_filenames": source_filenames,
                "source_brief": "\n".join(brief_lines) if brief_lines else "（无额外导读）",
                "formula_refs": formula_refs,
                "chunk_uids": [packet.digest_chunk_uid for packet in chapter_packets],
                "image_refs": image_refs,
            }
        )

    return assignments or build_chapter_assignments(outline_tree, clean_chunks)


async def generate_local_titles(content: str) -> list[str]:
    """Generate local outline titles with a light model."""

    prompt = LOCAL_OUTLINE_PROMPT.format(text=content[:3000])
    try:
        result = await acompletion(
            [{"role": "user", "content": prompt}],
            task_type=TaskType.DOCGEN_LIGHT,
        )
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        titles = json.loads(cleaned)
        if isinstance(titles, list):
            return _dedupe_titles([str(item) for item in titles], limit=6)
    except Exception as exc:
        logger.warning("generate_local_titles_failed", error=str(exc))
    return ["未分类内容"]


async def generate_global_outline(
    chunk_count: int,
    local_outlines_text: str,
    user_prompt: str | None = None,
    subject_context: str = "",
) -> dict:
    """Generate the global outline tree with the main doc model."""

    prompt = GLOBAL_OUTLINE_PROMPT.format(
        chunk_count=chunk_count,
        local_outlines=local_outlines_text,
        user_prompt=user_prompt or "（无额外要求）",
        subject_context=subject_context or "（未识别学科）",
    )
    try:
        result = await acompletion(
            [{"role": "user", "content": prompt}],
            task_type=TaskType.DOCGEN,
        )
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return json.loads(cleaned)
    except Exception as exc:
        logger.error("generate_global_outline_failed", error=str(exc))
        raise


def build_chapter_assignments(outline_tree: dict, clean_chunks: list[dict]) -> list[dict]:
    """Build chapter assignments from the outline tree and cleaned chunks."""

    chapters = outline_tree.get("chapters", [])
    assignments: list[dict] = []
    chapter_source_sets: list[set[int]] = []
    for chapter in chapters:
        source_indices: set[int] = set()
        for section in chapter.get("sections", []):
            for index in section.get("source_chunk_indices", []):
                if 0 <= index < len(clean_chunks):
                    source_indices.add(index)
        chapter_source_sets.append(source_indices)

    chapter_specific_batches: dict[int, str] = {}
    chunk_to_chapter_positions: dict[int, list[int]] = {}
    for chapter_position, source_indices in enumerate(chapter_source_sets):
        if len(source_indices) != 1:
            continue
        chunk_index = next(iter(source_indices))
        chunk_to_chapter_positions.setdefault(chunk_index, []).append(chapter_position)

    for chunk_index, chapter_positions in chunk_to_chapter_positions.items():
        if len(chapter_positions) <= 1:
            continue
        if any(chapter_source_sets[position] != {chunk_index} for position in chapter_positions):
            continue
        chunk_content = str(clean_chunks[chunk_index]["content"])
        split_batches = _split_content_batches(chunk_content, len(chapter_positions))
        if len(split_batches) <= 1:
            continue
        for chapter_position, batch in zip(chapter_positions, split_batches):
            chapter_specific_batches[chapter_position] = batch

    for chapter_position, chapter in enumerate(chapters):
        chapter_index = chapter.get("chapter_index", 0)
        chapter_title = chapter.get("title", f"第{chapter_index}章")
        sections = chapter.get("sections", [])
        sorted_indices = sorted(chapter_source_sets[chapter_position])
        source_chunks = [clean_chunks[index] for index in sorted_indices]
        source_file_ids = [chunk.get("file_id", 0) for chunk in source_chunks]
        source_filenames = [str(chunk.get("source_filename", "")) for chunk in source_chunks]
        section_titles = [
            str(section.get("title", "")).strip()
            for section in sections
            if str(section.get("title", "")).strip()
        ]
        assigned_batch = chapter_specific_batches.get(chapter_position)
        source_contents = [assigned_batch] if assigned_batch is not None else [chunk["content"] for chunk in source_chunks]
        use_section_batches = len(source_contents) == 1 and len(sections) > 1
        section_batches = _split_content_batches(source_contents[0], len(sections)) if use_section_batches else []

        section_payloads: list[dict] = []
        for section_index, section in enumerate(sections, start=1):
            section_indices = [
                index
                for index in section.get("source_chunk_indices", [])
                if 0 <= index < len(clean_chunks)
            ]
            if use_section_batches and section_batches:
                batch = section_batches[min(section_index - 1, len(section_batches) - 1)]
                section_contents = [batch]
                section_file_ids = list(source_file_ids)
            else:
                section_contents = [clean_chunks[index]["content"] for index in section_indices]
                section_file_ids = [clean_chunks[index].get("file_id", 0) for index in section_indices]
                if not section_contents and source_contents:
                    section_contents = list(source_contents)
                    section_file_ids = list(source_file_ids)
            section_payloads.append(
                {
                    "section_index": section_index,
                    "title": section.get("title", f"第{section_index}节"),
                    "source_contents": section_contents,
                    "source_file_ids": section_file_ids,
                }
            )

        formula_refs: list[str] = []
        for source_content in source_contents:
            formula_refs.extend(extract_formula_candidates(source_content, limit=4))
        formula_refs = _dedupe_formula_refs(formula_refs, limit=10)

        brief_lines: list[str] = []
        if assigned_batch is not None and sorted_indices:
            index = sorted_indices[0]
            filename = str(source_chunks[0].get("source_filename", f"chunk_{index}"))
            preview = build_chunk_preview(assigned_batch, max_chars=180)
            brief_lines.append(f"- 材料块 {index} / {filename}: {preview}")
        else:
            for index, chunk in zip(sorted_indices, source_chunks):
                preview = build_chunk_preview(chunk["content"], max_chars=180)
                filename = str(chunk.get("source_filename", f"chunk_{index}"))
                brief_lines.append(f"- 材料块 {index} / {filename}: {preview}")

        assignments.append(
            {
                "chapter_index": chapter_index,
                "title": chapter_title,
                "sections": sections,
                "section_titles": section_titles,
                "section_payloads": section_payloads,
                "source_contents": source_contents,
                "source_file_ids": source_file_ids,
                "source_filenames": source_filenames,
                "source_brief": "\n".join(brief_lines) if brief_lines else "（无额外导读）",
                "formula_refs": formula_refs,
            }
        )

    return assignments
