"""DocGen 工作流状态定义。"""

from __future__ import annotations

from typing import Any, TypedDict


class DocGenState(TypedDict, total=False):
    """DocGen 知识文档生成流水线状态。"""

    subject: str
    job_id: int
    file_ids: list[int]

    # ── 阶段一产出：数据清洗 ──
    clean_chunks: list[dict[str, Any]]
    # 每项 = {"file_id": int, "content": str, "source_filename": str}

    # ── 阶段二产出：全局目录树 ──
    outline_tree: dict[str, Any]
    # JSON 目录树，格式见 GLOBAL_OUTLINE_PROMPT
    chapter_assignments: list[dict[str, Any]]
    # 每项 = {"chapter_index": int, "title": str, "sections": [...], "source_contents": [str]}

    # ── 阶段三产出：多智能体撰写 ──
    chapter_drafts: list[dict[str, Any]]
    # 每项 = {"chapter_index": int, "title": str, "markdown": str}

    # ── 阶段四产出：元数据注入与落库 ──
    doc_ids: list[int]
    merged_markdown: str
    merged_path: str

    # ── 错误 ──
    error: str | None


__all__ = ["DocGenState"]
