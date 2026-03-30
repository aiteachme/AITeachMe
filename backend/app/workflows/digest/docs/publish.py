"""Helpers for staging and publishing knowledge docs in unified builds."""

from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime

from pydantic import BaseModel, Field

from app.core.database import managed_session
from app.models.knowledge_doc import KnowledgeDoc
from app.repositories.knowledge import docgen_repo
from app.utils.docgen_store import (
    KnowledgeDocsManifest,
    clear_published_knowledge_docs_files,
    update_knowledge_build_status,
    write_knowledge_manifest,
)
from app.utils.path_helpers import (
    build_knowledge_doc_build_path,
    build_knowledge_doc_path,
    build_knowledge_docs_build_dir,
    build_knowledge_docs_dir,
    build_merged_knowledge_base_build_path,
    build_merged_knowledge_base_path,
)
from app.utils.time import utcnow
from app.workflows.common.runtime import cancel_tasks_and_drain


class StagedKnowledgeDocs(BaseModel):
    """Staged knowledge-doc outputs waiting for unified publish."""

    merged_markdown: str = ""
    built_paths: list[tuple[int, str]] = Field(default_factory=list)


def count_words(text: str) -> int:
    """Return a simple CJK-friendly word count for markdown content."""

    return len(text.replace(" ", "").replace("\n", ""))


def _demote_markdown_headings(markdown: str, *, levels: int) -> str:
    lines: list[str] = []
    for line in markdown.splitlines():
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            lines.append(line)
            continue
        prefix = line[: len(line) - len(stripped)]
        hashes, _, title = stripped.partition(" ")
        if not title:
            lines.append(line)
            continue
        demoted_level = min(6, len(hashes) + levels)
        lines.append(f"{prefix}{'#' * demoted_level} {title}")
    return "\n".join(lines).strip()


def build_merged_markdown(chapters: list[dict]) -> str:
    """Merge chapter markdown into the published knowledge-doc layout."""

    header = [
        "# 知识文档总览",
        "",
    ]

    separator = "\n\n---\n\n"
    body: list[str] = []
    for chapter in chapters:
        markdown = str(chapter.get("markdown", ""))
        curriculum_path = list(chapter.get("curriculum_path", []))
        if curriculum_path:
            body.extend(
                [
                    f"{'#' * min(6, level + 2)} {title}"
                    for level, title in enumerate(curriculum_path)
                ]
            )
            body.append("")
            body.append(
                _demote_markdown_headings(markdown, levels=len(curriculum_path) + 1)
            )
        else:
            body.append(markdown)
    return "\n".join(header) + separator + separator.join(body) + "\n"


async def stage_knowledge_docs(
    *,
    subject: str,
    chapter_metadatas: list[dict],
) -> StagedKnowledgeDocs:
    """Write chapter markdown into the staging directory only."""

    if not chapter_metadatas:
        return StagedKnowledgeDocs()

    sorted_chapters = sorted(chapter_metadatas, key=lambda item: item.get("chapter_index", 0))
    build_dir = build_knowledge_docs_build_dir(subject)
    build_dir.mkdir(parents=True, exist_ok=True)

    chapter_write_tasks: list[asyncio.Task[None]] = []
    built_paths: list[tuple[int, str]] = []
    for index, chapter in enumerate(sorted_chapters):
        chapter_index = int(chapter.get("chapter_index", index + 1))
        chapter_title = str(chapter.get("title", f"第{chapter_index}章"))
        chapter_markdown = str(chapter.get("markdown", ""))
        build_path = build_knowledge_doc_build_path(subject, chapter_index, chapter_title)
        chapter_write_tasks.append(
            asyncio.create_task(
                asyncio.to_thread(build_path.write_text, chapter_markdown, encoding="utf-8")
            )
        )
        built_paths.append((chapter_index, chapter_title))

    try:
        if chapter_write_tasks:
            await asyncio.gather(*chapter_write_tasks)
    except asyncio.CancelledError:
        await cancel_tasks_and_drain(chapter_write_tasks)
        raise

    merged_markdown = build_merged_markdown(sorted_chapters)
    build_merged_path = build_merged_knowledge_base_build_path(subject)
    await asyncio.to_thread(build_merged_path.write_text, merged_markdown, encoding="utf-8")
    update_knowledge_build_status(
        subject,
        status="running",
        stage="doc_lane_staged",
        draft_available=bool(merged_markdown.strip()),
        draft_updated_at=utcnow(),
        staged_chapter_count=len(sorted_chapters),
    )
    return StagedKnowledgeDocs(merged_markdown=merged_markdown, built_paths=built_paths)


def publish_staged_knowledge_docs(
    *,
    subject: str,
    chapter_metadatas: list[dict],
    chapter_assignments: list[dict],
    user_prompt: str | None,
    requested_at: datetime,
    version_no: int = 1,
    build_session_id: str | None = None,
) -> list[int]:
    """Promote staged chapter markdown to live outputs and persist metadata."""

    if not chapter_metadatas:
        return []

    sorted_chapters = sorted(chapter_metadatas, key=lambda item: item.get("chapter_index", 0))
    published_dir = build_knowledge_docs_dir(subject)
    published_dir.mkdir(parents=True, exist_ok=True)
    clear_published_knowledge_docs_files(subject)

    for index, chapter in enumerate(sorted_chapters):
        chapter_index = int(chapter.get("chapter_index", index + 1))
        chapter_title = str(chapter.get("title", f"第{chapter_index}章"))
        build_path = build_knowledge_doc_build_path(subject, chapter_index, chapter_title)
        final_path = build_knowledge_doc_path(subject, chapter_index, chapter_title)
        shutil.move(str(build_path), str(final_path))

    shutil.move(
        str(build_merged_knowledge_base_build_path(subject)),
        str(build_merged_knowledge_base_path(subject)),
    )

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
    update_knowledge_build_status(
        subject,
        requested_at=requested_at,
        status="running",
        stage="publishing",
        error_message=None,
        draft_available=False,
        draft_updated_at=None,
        staged_chapter_count=len(sorted_chapters),
        published_doc_count=len(sorted_chapters),
    )

    docs_to_create: list[KnowledgeDoc] = []
    for index, chapter in enumerate(sorted_chapters):
        chapter_index = int(chapter.get("chapter_index", index + 1))
        chapter_title = str(chapter.get("title", f"第{chapter_index}章"))
        chapter_markdown = str(chapter.get("markdown", ""))
        summary = str(chapter.get("summary", ""))
        tags = chapter.get("tags", [])
        source_file_ids = list(chapter.get("source_file_ids", []))
        if not source_file_ids and index < len(chapter_assignments):
            source_file_ids = list(chapter_assignments[index].get("source_file_ids", []))

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
                word_count=count_words(chapter_markdown),
                version=version_no,
                version_no=version_no,
                build_session_id=build_session_id,
                is_current=True,
                status="published",
            )
        )

    with managed_session() as session:
        docgen_repo.delete_docs_by_subject(session, subject)
        created_docs = docgen_repo.bulk_create_knowledge_docs(session, docs_to_create)
    update_knowledge_build_status(
        subject,
        requested_at=requested_at,
        status="completed",
        stage="completed",
        error_message=None,
        draft_available=False,
        draft_updated_at=None,
        staged_chapter_count=len(sorted_chapters),
        published_doc_count=len(created_docs),
    )
    return [doc.id for doc in created_docs if doc.id is not None]
