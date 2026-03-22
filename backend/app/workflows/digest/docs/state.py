"""DocGen 工作流状态定义（Fan-Out 版本）。"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class DocGenState(TypedDict, total=False):
    """DocGen 知识文档生成流水线状态。

    带 ``Annotated[..., operator.add]`` 的字段支持 LangGraph
    Fan-Out → Fan-In 自动聚合。
    """

    # ── 基础 ──
    subject: str
    job_id: int
    file_ids: list[int]
    user_prompt: str | None

    # ── load_files 产出 ──
    raw_chunks: list[dict[str, Any]]
    # 每项 = {"file_id": int, "content": str, "source_filename": str}

    # ── cleanse 产出 ──
    clean_chunks: list[dict[str, Any]]

    # ── outline_map 产出 ──
    local_outlines: list[dict[str, Any]]
    # 每项 = {"chunk_index": int, "source_filename": str, "titles": [str]}

    # ── outline_reduce 产出 ──
    outline_tree: dict[str, Any]
    chapter_assignments: list[dict[str, Any]]

    # ── Fan-Out 汇聚字段（operator.add → 自动合并列表）──
    chapter_drafts: Annotated[list[dict[str, Any]], operator.add]
    chapter_reviews: Annotated[list[dict[str, Any]], operator.add]
    chapter_metadatas: Annotated[list[dict[str, Any]], operator.add]

    # ── finalize_assemble 产出 ──
    doc_ids: list[int]
    merged_markdown: str
    merged_path: str

    # ── 错误 ──
    error: str | None


__all__ = ["DocGenState"]
