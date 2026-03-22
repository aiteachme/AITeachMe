"""节点：Outline Reduce — 全局统筹 + chapter_assignments 组装。

Reads DB: ``docgen_job``.
Writes DB: ``docgen_job`` progress / chapter counts.
Writes FS: writes outline summaries and chapter assignments into ``docgen_intermediate/``.
Idempotency: reruns overwrite the same JSON intermediates for the active docgen job.
"""

from __future__ import annotations

import json
from time import perf_counter

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
from app.workflows.digest.docs.strategy import DocGenExecutionStrategy

logger = structlog.get_logger()


def build_outline_reduce_node(*, context: WorkflowContext, strategy: DocGenExecutionStrategy):
    """构建全局目录树 Reduce 节点。"""

    async def outline_reduce_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        node_logger = context.get_logger().bind(node="outline_reduce")
        node_logger.info(
            "outline_reduce_started",
            clean_chunk_count=len(state.get("clean_chunks", [])),
            local_outline_count=len(state.get("local_outlines", [])),
        )

        subject = state["subject"]
        job_id = state["job_id"]
        clean_chunks = state.get("clean_chunks", [])
        local_outlines = state.get("local_outlines", [])
        user_prompt = state.get("user_prompt")

        with managed_session() as session:
            docgen_repo.update_docgen_job(
                session, job_id, current_step="outlining_reduce", progress=32,
            )

        # 拼接局部摘要
        local_text = "\n".join(
            (
                f"文本块 {item['chunk_index']}（来源：{item['source_filename']}）\n"
                f"标题候选：{', '.join(item['titles']) or '（无）'}\n"
                f"内容预览：{item.get('preview', '（无预览）')}"
            )
            for item in local_outlines
        )

        outline_plan = strategy.plan_outline(
            chunk_count=len(clean_chunks),
            local_outlines=local_outlines,
            user_prompt=user_prompt,
        )

        if outline_plan.mode == "local_fast_path":
            first_outline = local_outlines[0] if local_outlines else {}
            first_titles = list(first_outline.get("titles", []))
            chapter_title = first_titles[0] if first_titles else clean_chunks[0].get("source_filename", "第1章")
            section_titles = first_titles[1:5] or ["全部内容"]
            outline_tree = {
                "chapters": [{
                    "chapter_index": 1,
                    "title": chapter_title,
                    "sections": [
                        {"title": title, "source_chunk_indices": [0]}
                        for title in section_titles
                    ],
                }]
            }
            llm_calls_total = 0
            node_logger.info(
                "outline_reduce_fast_path",
                chapter_title=chapter_title,
                section_count=len(section_titles),
                reason=outline_plan.reason,
            )
        else:
            # 全局 LLM 统筹
            try:
                node_logger.info("outline_reduce_planned", mode=outline_plan.mode, reason=outline_plan.reason)
                outline_tree = await generate_global_outline(
                    chunk_count=len(clean_chunks),
                    local_outlines_text=local_text,
                    user_prompt=user_prompt,
                )
                llm_calls_total = 1
            except Exception:
                # 兜底
                llm_calls_total = 0
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
                session,
                job_id,
                current_step="drafting",
                progress=40,
                total_chapters=len(chapter_assignments),
                completed_chapters=0,
            )

        outline_ms = int((perf_counter() - started_at) * 1000)
        node_logger.info(
            "outline_reduce_done",
            chapters=len(chapter_assignments),
            outline_ms=outline_ms,
            llm_calls_total=llm_calls_total,
        )
        return {
            "outline_tree": outline_tree,
            "chapter_assignments": chapter_assignments,
            "outline_ms": outline_ms,
            "llm_calls_total": llm_calls_total,
        }

    return outline_reduce_node
