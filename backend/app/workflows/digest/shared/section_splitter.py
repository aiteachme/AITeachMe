"""Section splitting for the shared digest prepare layer."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from app.workflows.digest.shared.models import SectionPacket

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
INLINE_FORMULA_PATTERN = re.compile(r"\$([^$\n]{1,160})\$")
BLOCK_FORMULA_PATTERN = re.compile(r"\$\$([^$]{1,400})\$\$")
IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)|<img[^>]+src=[\"']([^\"']+)[\"']", re.IGNORECASE)
QUESTION_MARKERS = (
    "question",
    "exercise",
    "example",
    "题",
    "练习",
    "例",
)
TOKEN_PATTERN = re.compile(r"[A-Za-z]{2,}|[\u4e00-\u9fff]{2,}")


def split_into_sections(content: str, file_id: int, filename: str) -> list[SectionPacket]:
    """Split one normalized markdown source into canonical section packets."""

    stripped = content.strip()
    if not stripped:
        return []

    headings = list(HEADING_PATTERN.finditer(stripped))
    if not headings:
        return [
            _build_section_packet(
                content=stripped,
                file_id=file_id,
                filename=filename,
                chunk_index=0,
                title=Path(filename).stem or "Untitled",
                level=1,
                header_path=Path(filename).stem or "Untitled",
            )
        ]

    sections: list[SectionPacket] = []
    first_start = headings[0].start()
    if first_start > 0:
        preamble = stripped[:first_start].strip()
        if preamble:
            sections.append(
                _build_section_packet(
                    content=preamble,
                    file_id=file_id,
                    filename=filename,
                    chunk_index=len(sections),
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
        header_path = _build_header_path(headings, index)
        sections.append(
            _build_section_packet(
                content=section_content,
                file_id=file_id,
                filename=filename,
                chunk_index=len(sections),
                title=title,
                level=level,
                header_path=header_path,
            )
        )
    return sections


def _build_section_packet(
    *,
    content: str,
    file_id: int,
    filename: str,
    chunk_index: int,
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
