"""Helpers for staging and publishing knowledge docs."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from app.models.knowledge_doc import KnowledgeDoc
from app.repositories.knowledge import docgen_repo
from app.shared.infra.database import managed_session
from app.workflows.digest.common.pedagogy import resolve_effective_chapter_title
from app.workflows.digest.common.pedagogy import build_document_overview as build_learning_document_overview
from app.shared.infra.storage import get_content_store, run_store_sync
from app.shared.infra.tools.builtin.markdown_processing import (
    build_reference_section,
    count_words,
    normalize_source_details,
    normalize_mermaid_blocks,
)
from app.utils.docgen_store import (
    KnowledgeDocsManifest,
    clear_current_published_knowledge_docs_files,
    update_knowledge_build_status,
    write_knowledge_manifest,
)
from app.utils.path_helpers import sanitize_doc_title
from app.utils.time import utcnow
from app.shared.infra.workflow.runtime import cancel_tasks_and_drain


class StagedKnowledgeDocs(BaseModel):
    """Staged knowledge-doc outputs waiting for final publish."""

    merged_markdown: str = ""
    built_paths: list[tuple[int, str]] = Field(default_factory=list)


def _chapter_merge_score(chapter: dict) -> tuple[int, int, int, int]:
    markdown = str(chapter.get("markdown") or "")
    summary = str(chapter.get("summary") or "")
    source_count = len(list(chapter.get("source_details") or []))
    return (
        1 if markdown.strip() else 0,
        count_words(markdown),
        source_count,
        len(summary),
    )


def _dedupe_chapter_metadatas(chapters: list[dict]) -> list[dict]:
    best_by_index: dict[int, dict] = {}
    for chapter in chapters:
        chapter_index = int(chapter.get("chapter_index", 0) or 0)
        existing = best_by_index.get(chapter_index)
        if existing is None or _chapter_merge_score(chapter) >= _chapter_merge_score(existing):
            best_by_index[chapter_index] = chapter
    return [best_by_index[index] for index in sorted(best_by_index)]


def _prepare_chapter_markdown(markdown: str) -> str:
    return _ensure_chapter_structure(normalize_mermaid_blocks(markdown))


def _ensure_chapter_structure(markdown: str) -> str:
    """Keep published docs readable: one h1, at least one h2."""

    cleaned = str(markdown or "").strip()
    if not cleaned:
        return ""

    lines = cleaned.splitlines()
    first_heading_index = next(
        (index for index, line in enumerate(lines) if line.lstrip().startswith("#")),
        None,
    )
    if first_heading_index is None:
        lines.insert(0, "# 本章内容")
    elif not lines[first_heading_index].lstrip().startswith("# "):
        title = lines[first_heading_index].lstrip("#").strip() or "本章内容"
        lines[first_heading_index] = f"# {title}"

    if not any(line.startswith("## ") for line in lines):
        insert_at = 1
        while insert_at < len(lines) and not lines[insert_at].strip():
            insert_at += 1
        lines.insert(insert_at, "## 核心内容")
        lines.insert(insert_at + 1, "")

    return "\n".join(lines).strip() + "\n"



def build_merged_markdown(
    chapters: list[dict],
    *,
    document_context: dict[str, object] | None = None,
) -> str:
    """Merge chapter markdown into the published knowledge-doc layout."""

    deduped_chapters = _dedupe_chapter_metadatas(chapters)
    include_sources = bool((document_context or {}).get("include_sources", True))
    overview = _ensure_document_overview_structure(
        build_learning_document_overview(
        subject=str((document_context or {}).get("subject") or "未命名学科"),
        subject_display_name=str((document_context or {}).get("subject_display_name") or ""),
        digest_mode=str((document_context or {}).get("digest_mode") or ""),
        user_goal=str((document_context or {}).get("user_goal") or ""),
        plan_summary=str((document_context or {}).get("plan_summary") or ""),
        source_strategy=str((document_context or {}).get("source_strategy") or ""),
        chapters=deduped_chapters,
        )
    )
    separator = "\n\n---\n\n"
    body: list[str] = [overview.strip()]
    all_source_details: list[dict[str, object]] = []
    for chapter in deduped_chapters:
        markdown = _prepare_chapter_markdown(str(chapter.get("markdown", "")).strip())
        all_source_details.extend(list(chapter.get("source_details") or []))
        if markdown:
            body.append(markdown)
    if include_sources:
        reference_block = build_reference_section(all_source_details).strip()
        if reference_block:
            body.append(reference_block)
    return normalize_mermaid_blocks(separator.join(body).strip()) + "\n"


def _ensure_document_overview_structure(markdown: str) -> str:
    cleaned = str(markdown or "").strip()
    if not cleaned.startswith("# "):
        cleaned = "# 知识文档总览\n\n" + cleaned.lstrip("# \n")
    if "\n## " not in cleaned:
        lines = cleaned.splitlines()
        lines.insert(2 if len(lines) > 1 else len(lines), "## 这份文档怎么读")
        lines.insert(3 if len(lines) > 2 else len(lines), "")
        cleaned = "\n".join(lines)
    return cleaned.strip()



def _build_chapter_key(subject: str, chapter_index: int, title: str) -> str:
    safe_title = sanitize_doc_title(title)
    return f"{subject}/knowledge_markdowns/chapter_{chapter_index:02d}_{safe_title}.md"


def _build_versioned_chapter_key(subject: str, version_no: int, chapter_index: int, title: str) -> str:
    safe_title = sanitize_doc_title(title)
    return f"{subject}/knowledge_markdowns/versions/v{version_no:04d}/chapter_{chapter_index:02d}_{safe_title}.md"


def _build_versioned_merged_key(subject: str, version_no: int) -> str:
    return f"{subject}/knowledge_markdowns/versions/v{version_no:04d}/merged_knowledge_base.md"


def _build_versioned_docgen_manifest_key(subject: str, version_no: int) -> str:
    return f"{subject}/knowledge_markdowns/versions/v{version_no:04d}/docgen_manifest.json"


def _build_current_docgen_manifest_key(subject: str) -> str:
    return f"{subject}/knowledge_markdowns/docgen_manifest.json"



def _staging_chapter_key(subject: str, chapter_index: int, title: str) -> str:
    safe_title = sanitize_doc_title(title)
    return f"{subject}/knowledge_markdowns/_build/chapter_{chapter_index:02d}_{safe_title}.md"



def _build_chapter_manifest(chapter: dict) -> dict[str, object]:
    source_details = normalize_source_details(list(chapter.get("source_details") or []))
    chapter_index = int(chapter.get("chapter_index", 0) or 0)
    effective_title = resolve_effective_chapter_title(chapter, chapter_index=chapter_index)
    return {
        "chapter_index": chapter_index,
        "title": effective_title,
        "resolved_title": str(chapter.get("resolved_title") or "").strip(),
        "provisional_title": str(chapter.get("title") or "").strip(),
        "summary": str(chapter.get("summary") or ""),
        "digest_mode": str(chapter.get("digest_mode") or ""),
        "course_type": str(chapter.get("course_type") or ""),
        "retrieval_profile": str(chapter.get("retrieval_profile") or ""),
        "teaching_action": str(chapter.get("teaching_action") or ""),
        "source_count": len(source_details),
        "source_details": source_details,
        "research_summary": str(chapter.get("research_summary") or ""),
        "research_ms": int(chapter.get("research_ms", 0) or 0),
        "local_hits": int(chapter.get("local_hits", 0) or 0),
        "web_hits": int(chapter.get("web_hits", 0) or 0),
        "fallback_used": bool(chapter.get("fallback_used", False)),
        "compression_mode": str(chapter.get("compression_mode") or ""),
        "executed_queries": list(chapter.get("executed_queries") or []),
        "base_queries": list(chapter.get("base_queries") or []),
        "planned_queries": list(chapter.get("planned_queries") or []),
        "fallback_queries": list(chapter.get("fallback_queries") or []),
        "query_count": int(chapter.get("query_count", 0) or 0),
        "read_url_count": int(chapter.get("read_url_count", 0) or 0),
        "document_count": int(chapter.get("document_count", 0) or 0),
        "purify_used": bool(chapter.get("purify_used", False)),
        "evidence_ledger": dict(chapter.get("evidence_ledger") or {}),
        "claim_ledger_ref": str(chapter.get("claim_ledger_ref") or ""),
        "claim_ledger": dict(chapter.get("claim_ledger") or {}),
        "claim_evidence_map": dict(chapter.get("claim_evidence_map") or {}),
        "conflict_report": dict(chapter.get("conflict_report") or {}),
        "chapter_review_report": dict(chapter.get("chapter_review_report") or {}),
        "conflict_warning_refs": list(chapter.get("conflict_warning_refs") or []),
        "quality_signals": dict(chapter.get("quality_signals") or {}),
        "asset_ids": list(chapter.get("asset_ids") or []),
        "practice_ids": list(chapter.get("practice_ids") or []),
        "warnings": list(chapter.get("warnings") or []),
    }



def _build_source_scope(chapter: dict) -> dict[str, object]:
    source_details = normalize_source_details(list(chapter.get("source_details") or []))
    external_sources = [item for item in source_details if not str(item.get("url") or "").startswith("local://")]
    local_sources = [item for item in source_details if str(item.get("url") or "").startswith("local://")]
    domains = sorted(
        {
            urlparse(str(item.get("url") or "")).netloc.strip().lower()
            for item in external_sources
            if urlparse(str(item.get("url") or "")).netloc.strip()
        }
    )
    return {
        "source_count": len(source_details),
        "local_source_count": len(local_sources),
        "external_source_count": len(external_sources),
        "domains": domains,
        "sources": source_details,
    }


async def stage_knowledge_docs(
    *,
    subject: str,
    chapter_metadatas: list[dict],
    document_context: dict[str, object] | None = None,
    docgen_artifacts: dict[str, Any] | None = None,
) -> StagedKnowledgeDocs:
    """Write chapter markdown into staging storage."""

    if not chapter_metadatas:
        return StagedKnowledgeDocs()

    cs = get_content_store()
    sorted_chapters = _dedupe_chapter_metadatas(
        sorted(chapter_metadatas, key=lambda item: item.get("chapter_index", 0))
    )
    built_paths: list[tuple[int, str]] = []
    write_tasks: list[asyncio.Task[None]] = []

    for index, chapter in enumerate(sorted_chapters, start=1):
        chapter_index = int(chapter.get("chapter_index", index))
        chapter_title = resolve_effective_chapter_title(chapter, chapter_index=chapter_index)
        chapter_markdown = _prepare_chapter_markdown(str(chapter.get("markdown") or ""))
        staging_key = _staging_chapter_key(subject, chapter_index, chapter_title)
        write_tasks.append(asyncio.create_task(cs.write_text(staging_key, chapter_markdown)))
        built_paths.append((chapter_index, chapter_title))

    try:
        if write_tasks:
            await asyncio.gather(*write_tasks)
    except asyncio.CancelledError:
        await cancel_tasks_and_drain(write_tasks)
        raise

    merged_markdown = build_merged_markdown(sorted_chapters, document_context=document_context)
    await cs.write_text(f"{subject}/knowledge_markdowns/_build/merged_knowledge_base.md", merged_markdown)
    if docgen_artifacts is not None:
        await cs.write_json_raw(f"{subject}/knowledge_markdowns/_build/docgen_manifest.json", docgen_artifacts)

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
    document_context: dict[str, object] | None,
    user_prompt: str | None,
    requested_at: datetime,
    version_no: int = 1,
    build_session_id: str | None = None,
    docgen_artifacts: dict[str, Any] | None = None,
) -> list[int]:
    """Promote staged chapter markdown to live outputs and persist metadata."""

    if not chapter_metadatas:
        return []

    cs = get_content_store()
    sorted_chapters = _dedupe_chapter_metadatas(
        sorted(chapter_metadatas, key=lambda item: item.get("chapter_index", 0))
    )
    with managed_session() as session:
        latest_version_no = docgen_repo.get_latest_version_no(session, subject)
    resolved_version_no = max(int(version_no or 0), latest_version_no + 1)
    package_key = f"{subject}:docgen:v{resolved_version_no:04d}"

    clear_current_published_knowledge_docs_files(subject)

    docs_to_create: list[KnowledgeDoc] = []
    for index, chapter in enumerate(sorted_chapters):
        chapter_index = int(chapter.get("chapter_index", index + 1))
        chapter_title = resolve_effective_chapter_title(chapter, chapter_index=chapter_index)
        chapter_markdown = _prepare_chapter_markdown(str(chapter.get("markdown") or ""))
        summary = str(chapter.get("summary") or "")
        tags = list(chapter.get("tags") or [])
        source_file_ids = list(chapter.get("source_file_ids") or [])
        if not source_file_ids and index < len(chapter_assignments):
            source_file_ids = list(chapter_assignments[index].get("source_file_ids") or [])

        final_key = _build_chapter_key(subject, chapter_index, chapter_title)
        archive_key = _build_versioned_chapter_key(
            subject,
            resolved_version_no,
            chapter_index,
            chapter_title,
        )
        run_store_sync(cs.write_text, archive_key, chapter_markdown)
        run_store_sync(cs.write_text, final_key, chapter_markdown)

        docs_to_create.append(
            KnowledgeDoc(
                subject=subject,
                chapter_index=chapter_index,
                title=chapter_title,
                summary=summary,
                markdown_content=chapter_markdown,
                markdown_path=archive_key,
                tags=json.dumps(tags, ensure_ascii=False),
                source_file_ids=json.dumps(source_file_ids),
                word_count=count_words(chapter_markdown),
                version=resolved_version_no,
                version_no=resolved_version_no,
                package_key=package_key,
                build_session_id=build_session_id,
                is_current=True,
                status="published",
                published_at=requested_at,
                digest_mode=str(chapter.get("digest_mode") or "") or None,
                manifest_json=json.dumps(_build_chapter_manifest(chapter), ensure_ascii=False),
                source_scope_json=json.dumps(_build_source_scope(chapter), ensure_ascii=False),
            )
        )

    merged_markdown = build_merged_markdown(sorted_chapters, document_context=document_context)
    run_store_sync(cs.write_text, _build_versioned_merged_key(subject, resolved_version_no), merged_markdown)
    run_store_sync(cs.write_text, cs.knowledge_doc_key(subject, "merged_knowledge_base.md"), merged_markdown)
    if docgen_artifacts is not None:
        versioned_manifest_key = _build_versioned_docgen_manifest_key(subject, resolved_version_no)
        current_manifest_key = _build_current_docgen_manifest_key(subject)
        run_store_sync(cs.write_json_raw, versioned_manifest_key, docgen_artifacts)
        run_store_sync(cs.write_json_raw, current_manifest_key, docgen_artifacts)
    run_store_sync(cs.delete_prefix, cs.knowledge_build_prefix(subject), default=0)

    manifest = KnowledgeDocsManifest(
        updated_at=requested_at,
        version_no=resolved_version_no,
        source_file_ids=sorted(
            {
                int(file_id)
                for chapter in sorted_chapters
                for file_id in chapter.get("source_file_ids", [])
            }
        ),
        prompt=user_prompt,
        chapter_count=len(sorted_chapters),
        chapter_titles=[
            resolve_effective_chapter_title(
                chapter,
                chapter_index=int(chapter.get("chapter_index", 0) or 0) or None,
            )
            for chapter in sorted_chapters
        ],
    )
    if docgen_artifacts is not None:
        manifest.docgen_manifest_key = _build_versioned_docgen_manifest_key(subject, resolved_version_no)
        manifest.merge_review_report = dict(docgen_artifacts.get("merge_review_report") or {})
    write_knowledge_manifest(subject, manifest)
    update_knowledge_build_status(
        subject,
        requested_at=requested_at,
        status="completed",
        stage="completed",
        error_message=None,
        draft_available=False,
        draft_updated_at=None,
        staged_chapter_count=len(sorted_chapters),
        published_doc_count=len(docs_to_create),
    )

    with managed_session() as session:
        current_docs = docgen_repo.get_docs_by_subject(session, subject, only_current=True)
        for doc in current_docs:
            doc.is_current = False
            doc.status = "superseded"
            doc.superseded_at = requested_at
            doc.updated_at = requested_at
            session.add(doc)
        for doc in docs_to_create:
            session.add(doc)
        session.commit()
        created_docs: list[KnowledgeDoc] = []
        for doc in docs_to_create:
            session.refresh(doc)
            created_docs.append(doc)

    return [doc.id for doc in created_docs if doc.id is not None]
