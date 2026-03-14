"""
基于标题的分块节点

按 H1/H2/H3 标题分块；H4~H6 保留在父块内。
无标题时生成根块（level=1）。
记录每个块的 header_path 和 chunk_index。
更新 Knowledge.pipeline_stage 为 chunked。

需求：7.5
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger()

# 匹配 H1~H6 标题行
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")


@dataclass
class ChunkData:
    """分块结果（尚未写入数据库的中间数据）"""
    title: str
    level: int  # 1~3
    header_path: str
    chunk_index: int
    content: str


def chunk_markdown(markdown: str) -> list[ChunkData]:
    """按 H1/H2/H3 标题层级切分 Markdown 文档。

    规则：
    - H1/H2/H3 标题触发新块
    - H4~H6 标题保留在当前块内容中
    - 无标题文档生成一个 root chunk（level=1）
    - 每个块记录 header_path（如 "第一章 > 1.1 节"）和 chunk_index

    Args:
        markdown: 清洗后的 Markdown 文本。

    Returns:
        ChunkData 列表，按文档顺序排列。
    """
    if not markdown or not markdown.strip():
        return [ChunkData(
            title="(root)",
            level=1,
            header_path="(root)",
            chunk_index=0,
            content="",
        )]

    lines = markdown.splitlines()
    chunks: list[ChunkData] = []

    # 追踪当前各级标题（用于构建 header_path）
    current_headers: dict[int, str] = {}  # level -> title
    current_title: str | None = None
    current_level: int | None = None
    current_lines: list[str] = []

    def _build_header_path(level: int, title: str) -> str:
        """根据当前标题层级构建 header_path。"""
        parts: list[str] = []
        for lv in range(1, level):
            if lv in current_headers:
                parts.append(current_headers[lv])
        parts.append(title)
        return " > ".join(parts)

    def _flush_chunk() -> None:
        """将当前累积的内容刷新为一个 chunk。"""
        nonlocal current_title, current_level, current_lines
        if current_title is None:
            return

        content = "\n".join(current_lines).strip()
        header_path = _build_header_path(current_level, current_title)
        chunks.append(ChunkData(
            title=current_title,
            level=current_level,
            header_path=header_path,
            chunk_index=len(chunks),
            content=content,
        ))
        current_lines = []

    for line in lines:
        match = _HEADING_RE.match(line)
        if match:
            hashes, title = match.group(1), match.group(2).strip()
            level = len(hashes)

            if level <= 3:
                # H1/H2/H3 触发新块
                _flush_chunk()
                current_title = title
                current_level = level
                # 更新标题追踪
                current_headers[level] = title
                # 清除更深层级的标题
                for lv in list(current_headers.keys()):
                    if lv > level:
                        del current_headers[lv]
            else:
                # H4~H6 保留在当前块内
                current_lines.append(line)
        else:
            current_lines.append(line)

    # 处理最后一个块
    if current_title is not None:
        _flush_chunk()
    elif current_lines:
        # 文档无任何 H1~H3 标题，生成 root chunk
        content = "\n".join(current_lines).strip()
        chunks.append(ChunkData(
            title="(root)",
            level=1,
            header_path="(root)",
            chunk_index=0,
            content=content,
        ))

    # 保底：至少一个 chunk
    if not chunks:
        chunks.append(ChunkData(
            title="(root)",
            level=1,
            header_path="(root)",
            chunk_index=0,
            content="",
        ))

    logger.info("chunking_complete", num_chunks=len(chunks))
    return chunks
