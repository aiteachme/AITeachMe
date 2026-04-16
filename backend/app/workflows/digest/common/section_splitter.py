"""Section splitting for the shared digest prepare layer."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from app.workflows.digest.common.models import SectionPacket

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
INLINE_FORMULA_PATTERN = re.compile(r"\$([^$\n]{1,160})\$")
BLOCK_FORMULA_PATTERN = re.compile(r"\$\$([^$]{1,400})\$\$")
IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)|<img[^>]+src=[\"']([^\"']+)[\"']", re.IGNORECASE)
PAGE_MARKER_PATTERN = re.compile(r"<!--\s*page\s*:\s*(\d+)\s*-->", re.IGNORECASE)
QUESTION_MARKERS = (
    "question",
    "exercise",
    "example",
    "题",
    "练习",
    "例",
)
TOKEN_PATTERN = re.compile(r"[A-Za-z]{2,}|[\u4e00-\u9fff]{2,}")
MAX_SECTION_CHARS = 1800
TARGET_SECTION_CHARS = 1200


def split_into_sections(content: str, file_id: int, filename: str) -> list[SectionPacket]:
    """Split one normalized markdown source into canonical section packets."""

    stripped = content.strip()
    if not stripped:
        return []

    headings = list(HEADING_PATTERN.finditer(stripped))
    if not headings:
        cleaned_content, page_num, _ = _extract_page_context(stripped, fallback_page_num=None)
        return _build_section_packets(
            content=cleaned_content,
            file_id=file_id,
            filename=filename,
            start_chunk_index=0,
            page_num=page_num,
            title=Path(filename).stem or "Untitled",
            level=1,
            header_path=Path(filename).stem or "Untitled",
        )

    sections: list[SectionPacket] = []
    current_page_num: int | None = None
    first_start = headings[0].start()
    if first_start > 0:
        preamble = stripped[:first_start].strip()
        if preamble:
            cleaned_preamble, section_page_num, current_page_num = _extract_page_context(
                preamble,
                fallback_page_num=current_page_num,
            )
            if cleaned_preamble:
                sections.extend(
                    _build_section_packets(
                        content=cleaned_preamble,
                        file_id=file_id,
                        filename=filename,
                        start_chunk_index=len(sections),
                        page_num=section_page_num,
                        title="Preamble",
                        level=1,
                        header_path="Preamble",
                    )
                )

    for index, heading_match in enumerate(headings):
        level = len(heading_match.group(1))
        title = heading_match.group(2).strip() or f"Section {index + 1}"
        start = heading_match.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(stripped)
        section_content = stripped[start:end].strip()
        section_content, section_page_num, current_page_num = _extract_page_context(
            section_content,
            fallback_page_num=current_page_num,
        )
        header_path = _build_header_path(headings, index)
        if not section_content:
            continue
        sections.extend(
            _build_section_packets(
                content=section_content,
                file_id=file_id,
                filename=filename,
                start_chunk_index=len(sections),
                page_num=section_page_num,
                title=title,
                level=level,
                header_path=header_path,
            )
        )
    return sections


def _extract_page_context(content: str, *, fallback_page_num: int | None) -> tuple[str, int | None, int | None]:
    page_markers = [int(match.group(1)) for match in PAGE_MARKER_PATTERN.finditer(content)]
    cleaned_content = PAGE_MARKER_PATTERN.sub("", content)
    cleaned_content = re.sub(r"\n{3,}", "\n\n", cleaned_content).strip()
    section_page_num = page_markers[0] if page_markers else fallback_page_num
    latest_page_num = page_markers[-1] if page_markers else fallback_page_num
    return cleaned_content, section_page_num, latest_page_num


def _build_section_packet(
    *,
    content: str,
    file_id: int,
    filename: str,
    chunk_index: int,
    page_num: int | None,
    title: str,
    level: int,
    header_path: str,
) -> SectionPacket:
    normalized_content = content.strip()
    uid_hash = hashlib.md5(
        f"{file_id}:{chunk_index}:{title}:{normalized_content}".encode("utf-8")
    ).hexdigest()[:10]
    digest_chunk_uid = f"rf_{file_id}_sec_{chunk_index:03d}_{uid_hash}"
    preview = normalized_content.replace("\n", " ").strip()[:200]
    if len(normalized_content) > 200:
        preview = preview.rstrip() + "..."

    return SectionPacket(
        digest_chunk_uid=digest_chunk_uid,
        source_file_id=file_id,
        source_filename=filename,
        chunk_index=chunk_index,
        page_num=page_num,
        title=title,
        header_path=header_path,
        level=level,
        normalized_content=normalized_content,
        preview=preview,
        char_count=len(normalized_content),
        formula_refs=_extract_formula_refs(normalized_content),
        question_block_count=_count_question_markers(title, normalized_content),
        header_candidates=_extract_header_candidates(title, header_path),
        image_refs=_extract_image_refs(normalized_content),
    )


def _build_section_packets(
    *,
    content: str,
    file_id: int,
    filename: str,
    start_chunk_index: int,
    page_num: int | None,
    title: str,
    level: int,
    header_path: str,
) -> list[SectionPacket]:
    parts = _split_large_content(content)
    packets: list[SectionPacket] = []
    for offset, part in enumerate(parts):
        part_title = title
        if len(parts) > 1:
            part_title = f"{title} (Part {offset + 1})"
        packets.append(
            _build_section_packet(
                content=part,
                file_id=file_id,
                filename=filename,
                chunk_index=start_chunk_index + offset,
                page_num=page_num,
                title=part_title,
                level=level,
                header_path=header_path,
            )
        )
    return packets


def _split_large_content(content: str) -> list[str]:
    normalized = content.strip()
    if len(normalized) <= MAX_SECTION_CHARS:
        return [normalized]

    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", normalized) if paragraph.strip()]
    if len(paragraphs) <= 1:
        return _split_plain_text(normalized)

    parts: list[str] = []
    current: list[str] = []
    current_chars = 0
    for paragraph in paragraphs:
        paragraph_chars = len(paragraph)
        if current and current_chars + paragraph_chars > TARGET_SECTION_CHARS:
            parts.append("\n\n".join(current).strip())
            current = []
            current_chars = 0
        current.append(paragraph)
        current_chars += paragraph_chars
    if current:
        parts.append("\n\n".join(current).strip())

    compact = [part for part in parts if part]
    if len(compact) == 1:
        return _split_plain_text(normalized)
    return compact


def _split_plain_text(content: str) -> list[str]:
    parts: list[str] = []
    cursor = 0
    total = len(content)
    while cursor < total:
        end = min(cursor + TARGET_SECTION_CHARS, total)
        if end < total:
            split_at = content.rfind("\n", cursor, end)
            if split_at <= cursor:
                split_at = content.rfind("。", cursor, end)
            if split_at <= cursor:
                split_at = end
            end = split_at
        chunk = content[cursor:end].strip()
        if chunk:
            parts.append(chunk)
        cursor = max(end, cursor + 1)
    return parts or [content]


def _build_header_path(headings: list[re.Match[str]], current_index: int) -> str:
    current_level = len(headings[current_index].group(1))
    path_parts = [headings[current_index].group(2).strip()]
    for index in range(current_index - 1, -1, -1):
        level = len(headings[index].group(1))
        if level < current_level:
            path_parts.insert(0, headings[index].group(2).strip())
            current_level = level
    return " > ".join(part for part in path_parts if part)


def _extract_formula_refs(content: str) -> list[str]:
    formulas = [
        match.group(1).strip()
        for match in BLOCK_FORMULA_PATTERN.finditer(content)
        if match.group(1).strip()
    ]
    formulas.extend(
        match.group(1).strip()
        for match in INLINE_FORMULA_PATTERN.finditer(content)
        if match.group(1).strip()
    )
    deduped: list[str] = []
    seen: set[str] = set()
    for formula in formulas:
        if formula in seen:
            continue
        seen.add(formula)
        deduped.append(formula)
        if len(deduped) >= 12:
            break
    return deduped


def _count_question_markers(title: str, content: str) -> int:
    haystack = f"{title}\n{content}".lower()
    return sum(haystack.count(marker) for marker in QUESTION_MARKERS)


def _extract_header_candidates(title: str, header_path: str) -> list[str]:
    matches = TOKEN_PATTERN.findall(f"{title} {header_path}")
    deduped: list[str] = []
    seen: set[str] = set()
    for match in matches:
        token = match.strip()
        if len(token) < 2:
            continue
        lowered = token.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(token)
        if len(deduped) >= 12:
            break
    return deduped


def _extract_image_refs(content: str) -> list[str]:
    refs: list[str] = []
    for match in IMAGE_PATTERN.finditer(content):
        raw = match.group(1) or match.group(2) or ""
        if not raw:
            continue
        refs.append(Path(raw.strip()).name)
    return list(dict.fromkeys(refs))

