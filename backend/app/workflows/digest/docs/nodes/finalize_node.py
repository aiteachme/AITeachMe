"""阶段四：元数据注入与物理组装节点。

提取摘要与标签，合并为最终知识库，双轨落库（DB + 磁盘）。
"""

from __future__ import annotations

import json

import structlog

from app.core.database import managed_session
from app.core.llm import acompletion
from app.core.model_router import TaskType
from app.models.knowledge_doc import KnowledgeDoc
from app.repositories.knowledge import docgen_repo
from app.services.upload_support import (
    build_knowledge_doc_path,
    build_knowledge_docs_dir,
    build_merged_knowledge_base_path,
)
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.state import DocGenState
from app.workflows.digest.prompts.docgen_prompts import METADATA_PROMPT

logger = structlog.get_logger()


async def _extract_metadata(markdown: str) -> dict:
    """使用 LLM 提取摘要和标签。"""

    # 截取前 3000 字作为输入
    truncated = markdown[:3000]
    prompt = METADATA_PROMPT.format(document=truncated)

    try:
        result = await acompletion(
            [{"role": "user", "content": prompt}],
            task_type=TaskType.DOCGEN_LIGHT,
        )
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        metadata = json.loads(cleaned)
        return {
            "summary": metadata.get("summary", "")[:200],
            "tags": metadata.get("tags", []),
        }
    except Exception as exc:
        logger.warning("finalize_metadata_failed", error=str(exc))
        return {"summary": "", "tags": []}


def _count_words(text: str) -> int:
    """统计字数（中文按字符，英文按空格分词）。"""

    # 简单统计：非空格字符数
    return len(text.replace(" ", "").replace("\n", ""))


def _build_merged_markdown(chapter_drafts: list[dict]) -> str:
    """将所有章节合并为一个带目录的完整知识库。"""

    toc_lines = ["# 📚 知识库目录\n"]
    for draft in chapter_drafts:
        title = draft.get("title", "")
        ch_idx = draft.get("chapter_index", 0)
        # 生成锚点（GitHub 风格）
        anchor = title.lower().replace(" ", "-").replace(".", "")
        toc_lines.append(f"- [第{ch_idx}章 {title}](#{anchor})")

    toc = "\n".join(toc_lines)
    separator = "\n\n---\n\n"

    body_parts: list[str] = []
    for draft in chapter_drafts:
        body_parts.append(draft.get("markdown", ""))

    return toc + separator + separator.join(body_parts) + "\n"


def build_finalize_node(*, context: WorkflowContext):
    """构建元数据注入与物理组装节点。"""

    async def finalize_node(state: DocGenState) -> dict:
        node_logger = context.get_logger().bind(node="finalize")
        node_logger.info("finalize_started")

        subject = state["subject"]
        job_id = state["job_id"]
        chapter_drafts = state.get("chapter_drafts", [])
        chapter_assignments = state.get("chapter_assignments", [])

        with managed_session() as session:
            docgen_repo.update_docgen_job(
                session, job_id, current_step="finalizing", progress=82,
            )

        if not chapter_drafts:
            return {"error": "没有章节草稿，无法组装。"}

        # 1) 确保输出目录存在
        docs_dir = build_knowledge_docs_dir(subject)
        docs_dir.mkdir(parents=True, exist_ok=True)

        # 2) 为每章提取元数据并落库
        doc_ids: list[int] = []

        for i, draft in enumerate(chapter_drafts):
            ch_index = draft.get("chapter_index", i + 1)
            ch_title = draft.get("title", f"第{ch_index}章")
            ch_markdown = draft.get("markdown", "")

            # 提取元数据
            metadata = await _extract_metadata(ch_markdown)
            summary = metadata.get("summary", "")
            tags = metadata.get("tags", [])

            # 获取来源文件 ID
            source_file_ids: list[int] = []
            if i < len(chapter_assignments):
                source_file_ids = chapter_assignments[i].get("source_file_ids", [])

            # 写入磁盘
            doc_path = build_knowledge_doc_path(subject, ch_index, ch_title)
            doc_path.write_text(ch_markdown, encoding="utf-8")

            # 写入数据库
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
                created_docs = docgen_repo.bulk_create_knowledge_docs(session, [doc])
                if created_docs:
                    doc_ids.append(created_docs[0].id)  # type: ignore[arg-type]

            node_logger.info(
                "finalize_chapter_done",
                chapter_index=ch_index,
                word_count=word_count,
                tag_count=len(tags),
            )

            # 更新进度
            with managed_session() as session:
                progress = 82 + int(15 * (i + 1) / len(chapter_drafts))
                docgen_repo.update_docgen_job(
                    session, job_id,
                    progress=progress,
                    completed_chapters=i + 1,
                )

        # 3) 合并为最终知识库
        merged_markdown = _build_merged_markdown(chapter_drafts)
        merged_path = build_merged_knowledge_base_path(subject)
        merged_path.write_text(merged_markdown, encoding="utf-8")

        # 4) 标记任务完成
        with managed_session() as session:
            docgen_repo.update_docgen_job(
                session, job_id,
                status="completed",
                progress=100,
                current_step="done",
            )

        node_logger.info(
            "finalize_completed",
            doc_count=len(doc_ids),
            merged_chars=len(merged_markdown),
            merged_path=str(merged_path),
        )
        return {
            "doc_ids": doc_ids,
            "merged_markdown": merged_markdown,
            "merged_path": str(merged_path),
        }

    return finalize_node
