"""节点：Outline Reduce — 全局统筹 + chapter_assignments 组装。

Reads DB: ``docgen_job``.
Writes DB: ``docgen_job`` progress / chapter counts.
Writes FS: writes outline summaries and chapter assignments into ``docgen_intermediate/``.
Idempotency: reruns overwrite the same JSON intermediates for the active docgen job.
"""

from __future__ import annotations

import json

import structlog

from app.core.database import managed_session
from app.repositories.knowledge import docgen_repo
from app.services.upload_support import build_docgen_intermediate_dir
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.services.outline_service import (
    build_chapter_assignments,
    generate_global_outline,
)
from app.workflows.digest.docs.state import DocGenState

logger = structlog.get_logger()


def build_outline_reduce_node(*, context: WorkflowContext):
    """构建全局目录树 Reduce 节点。"""

    async def outline_reduce_node(state: DocGenState) -> dict:
        node_logger = context.get_logger().bind(node="outline_reduce")
        node_logger.info("outline_reduce_started")

        subject = state["subject"]
        job_id = state["job_id"]
        clean_chunks = state.get("clean_chunks", [])
        local_outlines = state.get("local_outlines", [])

        with managed_session() as session:
            docgen_repo.update_docgen_job(
                session, job_id, current_step="outlining_reduce", progress=32,
            )

        # 拼接局部摘要
        local_text = "\n".join(
            f"文本块 {item['chunk_index']}（来源：{item['source_filename']}）：{', '.join(item['titles'])}"
            for item in local_outlines
        )

        # 全局 LLM 统筹
        try:
            outline_tree = await generate_global_outline(
                chunk_count=len(clean_chunks),
                local_outlines_text=local_text,
            )
        except Exception:
            # 兜底
            outline_tree = {
                "chapters": [
                    {
                        "chapter_index": i + 1,
                        "title": c.get("source_filename", f"第{i+1}章"),
                        "sections": [{"title": "全部内容", "source_chunk_indices": [i]}],
                    }
                    for i, c in enumerate(clean_chunks)
                ]
            }

        # 组装分配
        chapter_assignments = build_chapter_assignments(outline_tree, clean_chunks)

        # 保存中间产物
        out_dir = build_docgen_intermediate_dir(subject)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "outline_tree.json").write_text(
            json.dumps(outline_tree, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        (out_dir / "chapter_assignments.json").write_text(
            json.dumps(
                [{"ch": a["chapter_index"], "title": a["title"],
                  "secs": len(a["sections"]), "chars": sum(len(c) for c in a["source_contents"])}
                 for a in chapter_assignments],
                ensure_ascii=False, indent=2,
            ), encoding="utf-8",
        )

        with managed_session() as session:
            docgen_repo.update_docgen_job(
                session, job_id, progress=40, total_chapters=len(chapter_assignments),
            )

        node_logger.info("outline_reduce_done", chapters=len(chapter_assignments))
        return {"outline_tree": outline_tree, "chapter_assignments": chapter_assignments}

    return outline_reduce_node
