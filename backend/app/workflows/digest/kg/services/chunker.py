"""Chunking helpers for digest graph extraction."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

import structlog

logger = structlog.get_logger()

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
_QUESTION_START_RE = re.compile(
    r"^\s*(?:[-*+]\s*)?(?:(\d{1,4})\s*(?:[\u3001\.\uff0e\)])|\u7b2c\s*(\d{1,4})\s*\u9898)"
)
_ANSWER_SHEET_RE = re.compile(r"^\s*\d+\s*[-~\u2014]\s*\d+")
_MAX_QUESTIONS_PER_CHUNK = 6
_MAX_QUESTION_CHUNK_CHARS = 2800


@dataclass
class ChunkData:
    """A markdown chunk persisted as a DocumentChunk."""

    title: str
    level: int
    header_path: str
    chunk_index: int
    content: str

    def to_dict(self) -> dict[str, str | int]:
        return asdict(self)


@dataclass
class QuestionBlock:
    """A question-like block detected from flat markdown."""

    number: int | None
    stem: str
    content: str


def _build_header_path(current_headers: dict[int, str], level: int, title: str) -> str:
    parts = [current_headers[item_level] for item_level in range(1, level) if item_level in current_headers]
    parts.append(title)
    return " > ".join(parts)


def _split_by_headings(markdown: str) -> list[ChunkData]:
    if not markdown.strip():
        return [ChunkData(title="(root)", level=1, header_path="(root)", chunk_index=0, content="")]

    lines = markdown.splitlines()
    chunks: list[ChunkData] = []
    current_headers: dict[int, str] = {}
    current_title: str | None = None
    current_level: int | None = None
    current_lines: list[str] = []

    def flush_chunk() -> None:
        nonlocal current_title, current_level, current_lines
        if current_title is None or current_level is None:
            return

        chunks.append(
            ChunkData(
                title=current_title,
                level=current_level,
                header_path=_build_header_path(current_headers, current_level, current_title),
                chunk_index=len(chunks),
                content="\n".join(current_lines).strip(),
            )
        )
        current_lines = []

    for line in lines:
        match = _HEADING_RE.match(line)
        if match:
            level = len(match.group(1))
            title = match.group(2).strip()
            if level <= 3:
                flush_chunk()
                current_title = title
                current_level = level
                current_headers[level] = title
                for key in list(current_headers.keys()):
                    if key > level:
                        del current_headers[key]
                continue

        current_lines.append(line)

    if current_title is not None:
        flush_chunk()
    elif current_lines:
        chunks.append(
            ChunkData(
                title="(root)",
                level=1,
                header_path="(root)",
                chunk_index=0,
                content="\n".join(current_lines).strip(),
            )
        )

    return chunks


def _extract_question_number(line: str) -> int | None:
    match = _QUESTION_START_RE.match(line)
    if match is None:
        return None

    raw_number = match.group(1) or match.group(2)
    if raw_number is None:
        return None

    try:
        return int(raw_number)
    except ValueError:
        return None


def _clean_question_stem(line: str) -> str:
    text = _QUESTION_START_RE.sub("", line, count=1)
    text = re.sub(r"\s*(?:[\(\uff08][A-Da-d]\s*[\)\uff09])\s*$", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -*+")


def parse_question_blocks(markdown: str) -> list[QuestionBlock]:
    """Parse flat question-bank markdown into question blocks."""

    if not markdown.strip():
        return []

    blocks: list[QuestionBlock] = []
    current_lines: list[str] = []
    current_number: int | None = None

    def flush_block() -> None:
        nonlocal current_lines, current_number
        if not current_lines:
            return

        first_line = current_lines[0].strip()
        stem = _clean_question_stem(first_line)
        content = "\n".join(line.rstrip() for line in current_lines).strip()
        if not stem or not content or _ANSWER_SHEET_RE.match(first_line):
            current_lines = []
            current_number = None
            return

        blocks.append(QuestionBlock(number=current_number, stem=stem, content=content))
        current_lines = []
        current_number = None

    for line in markdown.splitlines():
        number = _extract_question_number(line)
        if number is not None:
            flush_block()
            current_lines = [line]
            current_number = number
            continue

        if current_lines:
            current_lines.append(line)

    flush_block()
    return blocks


def _is_question_bank_chunk(chunk: ChunkData, question_blocks: list[QuestionBlock]) -> bool:
    if len(question_blocks) < 3:
        return False

    return len(chunk.content) >= _MAX_QUESTION_CHUNK_CHARS or len(question_blocks) > _MAX_QUESTIONS_PER_CHUNK


def _format_question_range(question_blocks: list[QuestionBlock]) -> str:
    numbers = [block.number for block in question_blocks if block.number is not None]
    if not numbers:
        return f"{len(question_blocks)} questions"

    start = min(numbers)
    end = max(numbers)
    if start == end:
        return f"Question {start}"
    return f"Questions {start}-{end}"


def _split_question_bank_chunk(chunk: ChunkData, question_blocks: list[QuestionBlock]) -> list[ChunkData]:
    grouped_blocks: list[list[QuestionBlock]] = []
    current_group: list[QuestionBlock] = []
    current_chars = 0

    for block in question_blocks:
        block_chars = len(block.content)
        should_flush = (
            current_group
            and (
                len(current_group) >= _MAX_QUESTIONS_PER_CHUNK
                or current_chars + block_chars > _MAX_QUESTION_CHUNK_CHARS
            )
        )
        if should_flush:
            grouped_blocks.append(current_group)
            current_group = []
            current_chars = 0

        current_group.append(block)
        current_chars += block_chars

    if current_group:
        grouped_blocks.append(current_group)

    if len(grouped_blocks) <= 1:
        return [chunk]

    title_prefix = chunk.title if chunk.title != "(root)" else "Question bank"
    header_prefix = chunk.header_path if chunk.header_path != "(root)" else title_prefix
    split_chunks: list[ChunkData] = []

    for index, group in enumerate(grouped_blocks):
        range_label = _format_question_range(group)
        split_chunks.append(
            ChunkData(
                title=f"{title_prefix} / {range_label}",
                level=chunk.level,
                header_path=f"{header_prefix} > {range_label}",
                chunk_index=index,
                content="\n\n".join(block.content for block in group).strip(),
            )
        )

    return split_chunks


def _expand_question_bank_chunks(chunks: list[ChunkData]) -> list[ChunkData]:
    expanded: list[ChunkData] = []
    question_chunk_count = 0

    for chunk in chunks:
        question_blocks = parse_question_blocks(chunk.content)
        if _is_question_bank_chunk(chunk, question_blocks):
            split_chunks = _split_question_bank_chunk(chunk, question_blocks)
            question_chunk_count += max(len(split_chunks) - 1, 0)
            expanded.extend(split_chunks)
            continue

        expanded.append(chunk)

    reindexed = [
        ChunkData(
            title=chunk.title,
            level=chunk.level,
            header_path=chunk.header_path,
            chunk_index=index,
            content=chunk.content,
        )
        for index, chunk in enumerate(expanded)
    ]

    logger.info(
        "chunk_markdown_complete",
        chunk_count=len(reindexed),
        question_split_count=question_chunk_count,
    )
    return reindexed


def chunk_markdown(markdown: str) -> list[ChunkData]:
    """Chunk markdown by headings first, then split flat question banks."""

    heading_chunks = _split_by_headings(markdown)
    return _expand_question_bank_chunks(heading_chunks)


__all__ = ["ChunkData", "QuestionBlock", "chunk_markdown", "parse_question_blocks"]
