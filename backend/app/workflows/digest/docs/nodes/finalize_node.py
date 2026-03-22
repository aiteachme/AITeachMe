"""Finalize, publish, and persist knowledge docs outputs."""

from __future__ import annotations

import asyncio
import json
import shutil
from time import perf_counter

import structlog

from app.core.database import managed_session
from app.models.knowledge_doc import KnowledgeDoc
from app.repositories.knowledge import docgen_repo
from app.services.knowledge.docgen_store import (
    KnowledgeDocsManifest,
    clear_published_knowledge_docs_files,
    write_knowledge_manifest,
)
from app.services.upload_support import (
    build_knowledge_doc_build_path,
    build_knowledge_doc_path,
    build_knowledge_docs_build_dir,
    build_knowledge_docs_dir,
    build_merged_knowledge_base_build_path,
    build_merged_knowledge_base_path,
)
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.state import DocGenState

logger = structlog.get_logger()


def _count_words(text: str) -> int:
    return len(text.replace(" ", "").replace("\n", ""))


def _build_merged_markdown(chapters: list[dict]) -> str:
    toc = [
        "# 知识文档总览",
        "",
        "## 目录",
        "",
    ]
    for chapter in chapters:
        title = chapter.get("title", "")
        chapter_index = chapter.get("chapter_index", 0)
        toc.append(f"- 第{chapter_index}章 {title}")

    separator = "\n\n---\n\n"
    body = [chapter.get("markdown", "") for chapter in chapters]
    return "\n".join(toc) + separator + separator.join(body) + "\n"


def _publish_built_markdown(subject: str, built_paths: list[tuple[int, str]]) -> None:
    published_dir = build_knowledge_docs_dir(subject)
    published_dir.mkdir(parents=True, exist_ok=True)
    clear_published_knowledge_docs_files(subject)
    for chapter_index, title in built_paths:
        build_path = build_knowledge_doc_build_path(subject, chapter_index, title)
        final_path = build_knowledge_doc_path(subject, chapter_index, title)
        shutil.move(str(build_path), str(final_path))

    shutil.move(
        str(build_merged_knowledge_base_build_path(subject)),
        str(build_merged_knowledge_base_path(subject)),
    )


def build_finalize_assemble_node(*, context: WorkflowContext):
    """Build the final publish node."""

    async def finalize_assemble_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        node_logger = context.get_logger().bind(node="finalize_assemble")
        subject = state["subject"]
        chapter_metadatas = state.get("chapter_metadatas", [])
        chapter_assignments = state.get("chapter_assignments", [])
        user_prompt = state.get("user_prompt")
        requested_at = state["requested_at"]

        if not chapter_metadatas:
            return {"error": "没有章节数据，无法组装。"}

        sorted_chapters = sorted(chapter_metadatas, key=lambda item: item.get("chapter_index", 0))
        build_dir = build_knowledge_docs_build_dir(subject)
        build_dir.mkdir(parents=True, exist_ok=True)

        node_logger.info(
            "docgen_merging_docs",
            chapter_count=len(sorted_chapters),
            requested_at=requested_at.isoformat(),
        )

        docs_to_create: list[KnowledgeDoc] = []
        chapter_write_tasks: list[asyncio.Task[None]] = []
        built_paths: list[tuple[int, str]] = []

        for index, chapter in enumerate(sorted_chapters):
            chapter_index = chapter.get("chapter_index", index + 1)
            chapter_title = chapter.get("title", f"第{chapter_index}章")
            chapter_markdown = chapter.get("markdown", "")
            summary = chapter.get("summary", "")
            tags = chapter.get("tags", [])
            source_file_ids = chapter.get("source_file_ids", [])
            if not source_file_ids and index < len(chapter_assignments):
                source_file_ids = chapter_assignments[index].get("source_file_ids", [])

            build_path = build_knowledge_doc_build_path(subject, chapter_index, chapter_title)
            chapter_write_tasks.append(
                asyncio.create_task(
                    asyncio.to_thread(build_path.write_text, chapter_markdown, encoding="utf-8")
                )
            )
            built_paths.append((chapter_index, chapter_title))
            docs_to_create.append(
                KnowledgeDoc(
                    subject=subject,
                    chapter_index=chapter_index,
                    title=chapter_title,
                    summary=summary,
                    markdown_content=chapter_markdown,
                    markdown_path=str(build_knowledge_doc_path(subject, chapter_index, chapter_title)),
                    tags=json.dumps(tags, ensure_ascii=False),
                    source_file_ids=json.dumps(source_file_ids),
                    word_count=_count_words(chapter_markdown),
                    status="published",
                )
            )

        if chapter_write_tasks:
            await asyncio.gather(*chapter_write_tasks)

        merged_markdown = _build_merged_markdown(sorted_chapters)
        build_merged_path = build_merged_knowledge_base_build_path(subject)
        await asyncio.to_thread(build_merged_path.write_text, merged_markdown, encoding="utf-8")

        node_logger.info(
            "docgen_publishing_docs",
            chapter_count=len(built_paths),
            requested_at=requested_at.isoformat(),
        )
        _publish_built_markdown(subject, built_paths)

        manifest = KnowledgeDocsManifest(
            updated_at=requested_at,
            source_file_ids=sorted(
                {
                    file_id
                    for chapter in sorted_chapters
                    for file_id in chapter.get("source_file_ids", [])
                }
            ),
            prompt=user_prompt,
            chapter_count=len(sorted_chapters),
            chapter_titles=[str(chapter.get("title", "")) for chapter in sorted_chapters],
        )
        write_knowledge_manifest(subject, manifest)

        with managed_session() as session:
            docgen_repo.delete_docs_by_subject(session, subject)
            created_docs = docgen_repo.bulk_create_knowledge_docs(session, docs_to_create)

        finalize_ms = int((perf_counter() - started_at) * 1000)
        node_logger.info(
            "knowledge_build_completed",
            chapter_count=len(created_docs),
            merged_chars=len(merged_markdown),
            finalize_ms=finalize_ms,
            requested_at=requested_at.isoformat(),
        )
        return {
            "doc_ids": [doc.id for doc in created_docs if doc.id is not None],
            "merged_markdown": merged_markdown,
            "merged_path": str(build_merged_knowledge_base_path(subject)),
            "finalize_ms": finalize_ms,
        }

    return finalize_assemble_node
