"""Fan-Out 子节点：撰写单个章节（由 Send 分发）。

Reads DB: ``docgen_job``.
Writes DB: ``docgen_job`` progress.
Writes FS: writes chapter draft markdown into ``docgen_intermediate/``.
Idempotency: reruns overwrite the same draft file for the same chapter index.
"""

from __future__ import annotations

import structlog

from app.core.database import managed_session
from app.repositories.knowledge import docgen_repo
from app.services.upload_support import build_docgen_intermediate_dir
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.services.writer_service import (
    build_global_outline_summary,
    write_chapter,
)

logger = structlog.get_logger()


def build_draft_chapter_node(*, context: WorkflowContext):
    """构建单章撰写 Fan-Out 子节点。

    接收 Send 分发的 payload，包含单章所需全部信息。
    返回 ``chapter_drafts`` 列表（单元素），由 operator.add 汇聚。
    """

    async def draft_chapter_node(state: dict) -> dict:
        node_logger = context.get_logger().bind(node="draft_chapter")

        chapter = state["chapter"]
        job_id = state["job_id"]
        outline_tree = state.get("outline_tree", {})
        total_chapters = state.get("total_chapters", 1)
        user_prompt = state.get("user_prompt")
        prev_summary = state.get("prev_summary", "")
        next_preview = state.get("next_preview", "")
        subject = state.get("subject", "")

        ch_index = chapter["chapter_index"]
        ch_title = chapter.get("title", f"第{ch_index}章")
        source_contents = chapter.get("source_contents", [])
        source_text = "\n\n---\n\n".join(source_contents) if source_contents else "（无原始素材）"

        node_logger.info("draft_chapter_start", chapter_index=ch_index)

        global_outline_text = build_global_outline_summary(outline_tree)

        markdown = await write_chapter(
            chapter_title=ch_title,
            chapter_index=ch_index,
            total_chapters=total_chapters,
            global_outline_text=global_outline_text,
            user_prompt=user_prompt,
            prev_summary=prev_summary,
            next_preview=next_preview,
            source_content=source_text,
        )

        # 保存草稿中间产物
        if subject:
            out_dir = build_docgen_intermediate_dir(subject)
            out_dir.mkdir(parents=True, exist_ok=True)
            safe_title = ch_title.replace("/", "_").replace("\\", "_")[:30]
            (out_dir / f"draft_{ch_index:02d}_{safe_title}.md").write_text(
                markdown, encoding="utf-8",
            )

        # 更新进度
        with managed_session() as session:
            docgen_repo.update_docgen_job(session, job_id, progress=45 + ch_index * 3)

        node_logger.info("draft_chapter_done", chapter_index=ch_index, chars=len(markdown))
        return {
            "chapter_drafts": [{
                "chapter_index": ch_index,
                "title": ch_title,
                "markdown": markdown,
                "source_contents": source_contents,
            }],
        }

    return draft_chapter_node
