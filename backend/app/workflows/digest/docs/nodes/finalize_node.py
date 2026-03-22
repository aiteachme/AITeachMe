"""节点：最终组装 — 合并章节、双轨落库。

Reads DB: ``docgen_job``.
Writes DB: ``knowledge_doc`` and final ``docgen_job`` state.
Writes FS: writes chapter markdown files and the merged knowledge base under
``knowledge_docs/``.
Idempotency: reruns overwrite the same filesystem outputs and append/update job-linked
knowledge-doc rows for the active build.
"""

from __future__ import annotations

import json

import structlog

from app.core.database import managed_session
from app.models.knowledge_doc import KnowledgeDoc
from app.repositories.knowledge import docgen_repo
from app.services.upload_support import (
    build_knowledge_doc_path,
    build_knowledge_docs_dir,
    build_merged_knowledge_base_path,
)
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.state import DocGenState

logger = structlog.get_logger()


def _count_words(text: str) -> int:
    return len(text.replace(" ", "").replace("\n", ""))


def _build_merged_markdown(chapters: list[dict]) -> str:
    toc = ["# 📚 知识库目录\n"]
    for ch in chapters:
        title = ch.get("title", "")
        idx = ch.get("chapter_index", 0)
        anchor = title.lower().replace(" ", "-").replace(".", "")
        toc.append(f"- [第{idx}章 {title}](#{anchor})")

    sep = "\n\n---\n\n"
    body = [ch.get("markdown", "") for ch in chapters]
    return "\n".join(toc) + sep + sep.join(body) + "\n"


def build_finalize_assemble_node(*, context: WorkflowContext):
    """构建最终组装节点。"""

    async def finalize_assemble_node(state: DocGenState) -> dict:
        node_logger = context.get_logger().bind(node="finalize_assemble")
        node_logger.info("finalize_started")

        subject = state["subject"]
        job_id = state["job_id"]
        chapter_metadatas = state.get("chapter_metadatas", [])
        chapter_assignments = state.get("chapter_assignments", [])

        with managed_session() as session:
            docgen_repo.update_docgen_job(
                session, job_id, current_step="assembling", progress=85,
            )

        if not chapter_metadatas:
            return {"error": "没有章节数据，无法组装。"}

        # 按 chapter_index 排序
        sorted_chapters = sorted(chapter_metadatas, key=lambda c: c.get("chapter_index", 0))

        docs_dir = build_knowledge_docs_dir(subject)
        docs_dir.mkdir(parents=True, exist_ok=True)

        doc_ids: list[int] = []
        for i, ch in enumerate(sorted_chapters):
            ch_index = ch.get("chapter_index", i + 1)
            ch_title = ch.get("title", f"第{ch_index}章")
            ch_markdown = ch.get("markdown", "")
            summary = ch.get("summary", "")
            tags = ch.get("tags", [])

            # 来源文件 ID
            source_file_ids: list[int] = ch.get("source_file_ids", [])
            if not source_file_ids and i < len(chapter_assignments):
                source_file_ids = chapter_assignments[i].get("source_file_ids", [])

            # 写磁盘
            doc_path = build_knowledge_doc_path(subject, ch_index, ch_title)
            doc_path.write_text(ch_markdown, encoding="utf-8")

            # 写 DB
            word_count = _count_words(ch_markdown)
            doc = KnowledgeDoc(
                subject=subject,
                chapter_index=ch_index,
                title=ch_title,
                summary=summary,
                markdown_content=ch_markdown,
                markdown_path=str(doc_path),
                tags=json.dumps(tags, ensure_ascii=False),
                source_file_ids=json.dumps(source_file_ids),
                word_count=word_count,
                status="published",
            )
            with managed_session() as session:
                created = docgen_repo.bulk_create_knowledge_docs(session, [doc])
                if created:
                    doc_ids.append(created[0].id)  # type: ignore[arg-type]

            node_logger.info("chapter_persisted", ch=ch_index, words=word_count)

            with managed_session() as session:
                progress = 85 + int(12 * (i + 1) / len(sorted_chapters))
                docgen_repo.update_docgen_job(
                    session, job_id, progress=progress, completed_chapters=i + 1,
                )

        # 合并
        merged = _build_merged_markdown(sorted_chapters)
        merged_path = build_merged_knowledge_base_path(subject)
        merged_path.write_text(merged, encoding="utf-8")

        # 完成
        with managed_session() as session:
            docgen_repo.update_docgen_job(
                session, job_id, status="completed", progress=100, current_step="done",
            )

        node_logger.info("finalize_done", docs=len(doc_ids), merged_chars=len(merged))
        return {
            "doc_ids": doc_ids,
            "merged_markdown": merged,
            "merged_path": str(merged_path),
        }

    return finalize_assemble_node
