"""Markdown 切块器。"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

import structlog

logger = structlog.get_logger()

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")


@dataclass
class ChunkData:
    """单个切块数据。"""

    title: str
    level: int
    header_path: str
    chunk_index: int
    content: str

    def to_dict(self) -> dict[str, str | int]:
        """转为字典，方便写入 playground 输出。"""

        return asdict(self)


def chunk_markdown(markdown: str) -> list[ChunkData]:
    """按 H1/H2/H3 标题切块。"""

    if not markdown.strip():
        return [ChunkData(title="(root)", level=1, header_path="(root)", chunk_index=0, content="")]

    lines = markdown.splitlines()
    chunks: list[ChunkData] = []
    current_headers: dict[int, str] = {}
    current_title: str | None = None
    current_level: int | None = None
    current_lines: list[str] = []

    def build_header_path(level: int, title: str) -> str:
        parts = [current_headers[item_level] for item_level in range(1, level) if item_level in current_headers]
        parts.append(title)
        return " > ".join(parts)

    def flush_chunk() -> None:
        nonlocal current_title, current_level, current_lines
        if current_title is None or current_level is None:
            return
        chunks.append(
            ChunkData(
                title=current_title,
                level=current_level,
                header_path=build_header_path(current_level, current_title),
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

    logger.info("chunk_markdown_complete", chunk_count=len(chunks))
    return chunks
