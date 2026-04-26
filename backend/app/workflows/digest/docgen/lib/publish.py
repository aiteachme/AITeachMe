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
from app.shared.infra.storage import (
    get_content_store,
    resolve_subject_storage_scope,
    run_store_sync,
)
from app.shared.infra.tools.builtin.markdown_processing import (
    build_reference_section,
    count_words,
    normalize_markdown_rendering,
    normalize_source_details,
    normalize_mermaid_blocks,
)
from app.shared.infra.knowledge.build_store import (
    KnowledgeDocsManifest,
    clear_current_published_knowledge_docs_files,
    update_knowledge_build_status,
    write_knowledge_manifest,
)
from app.workflows.support.subjects.learning_context import update_subject_learning_context_from_docgen
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
    return _ensure_chapter_structure(normalize_mermaid_blocks(normalize_markdown_rendering(markdown)))


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
    cover_markdown: str | None = None,
) -> str:
    """Merge chapter markdown into the published knowledge-doc layout."""

    deduped_chapters = _dedupe_chapter_metadatas(chapters)
    include_sources = bool((document_context or {}).get("include_sources", True))
    overview = _ensure_document_overview_structure(
        build_learning_document_overview(
        subject=str((document_context or {}).get("subject") or "未命名学科"),
        subject_display_name=str((document_context or {}).get("subject_display_name") or ""),
        digest_mode=str((document_context or {}).get("digest_mode") or ""),
        user_prompt=str((document_context or {}).get("user_prompt") or ""),
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
    merged = separator.join(body).strip()
    if str(cover_markdown or "").strip():
        merged = f"{str(cover_markdown).strip()}\n\n{merged.lstrip()}".strip()
    return normalize_mermaid_blocks(merged.strip()) + "\n"


def _ensure_document_overview_structure(markdown: str) -> str:
    cleaned = str(markdown or "").strip()
    if not cleaned.startswith("# "):
        cleaned = "# 知识文档总览\n\n" + cleaned.lstrip("# \n")
    if "\n## 目录" not in cleaned and "\n## 目錄" not in cleaned:
        cleaned = _insert_toc_after_overview_intro(cleaned)
    return cleaned.strip()


def _insert_toc_after_overview_intro(markdown: str) -> str:
    lines = str(markdown or "").splitlines()
    if not lines:
        return "# 知识文档总览\n\n## 目录\n\n"
    insert_at = len(lines)
    for index, line in enumerate(lines[1:], start=1):
        if line.startswith("## "):
            insert_at = index
            break
    while insert_at > 0 and not lines[insert_at - 1].strip():
        insert_at -= 1
    toc_block = ["", "## 目录", ""]
    lines[insert_at:insert_at] = toc_block
    return "\n".join(lines).strip() + "\n"



def _build_chapter_key(namespace: str, chapter_index: int, title: str) -> str:
    safe_title = sanitize_doc_title(title)
    return f"{namespace}/knowledge_markdowns/chapter_{chapter_index:02d}_{safe_title}.md"


def _build_versioned_chapter_key(namespace: str, version_no: int, chapter_index: int, title: str) -> str:
    safe_title = sanitize_doc_title(title)
    return f"{namespace}/knowledge_markdowns/versions/v{version_no:04d}/chapter_{chapter_index:02d}_{safe_title}.md"


def _build_versioned_merged_key(namespace: str, version_no: int) -> str:
    return f"{namespace}/knowledge_markdowns/versions/v{version_no:04d}/merged_knowledge_base.md"


def _build_versioned_docgen_manifest_key(namespace: str, version_no: int) -> str:
    return f"{namespace}/knowledge_markdowns/versions/v{version_no:04d}/docgen_manifest.json"


def _build_current_docgen_manifest_key(namespace: str) -> str:
    return f"{namespace}/knowledge_markdowns/docgen_manifest.json"


def _staging_chapter_key(namespace: str, chapter_index: int, title: str) -> str:
    safe_title = sanitize_doc_title(title)
    return f"{namespace}/knowledge_markdowns/_build/chapter_{chapter_index:02d}_{safe_title}.md"



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


def _clean_source_file_ids(value: object) -> list[int]:
    raw_items = value if isinstance(value, list) else ([] if value is None else [value])
    cleaned: list[int] = []
    seen: set[int] = set()
    for item in raw_items:
        try:
            file_id = int(item)
        except (TypeError, ValueError):
            continue
        if file_id <= 0 or file_id in seen:
            continue
        seen.add(file_id)
        cleaned.append(file_id)
    return cleaned


def _assignments_by_chapter_index(chapter_assignments: list[dict]) -> dict[int, dict]:
    indexed: dict[int, dict] = {}
    for fallback_index, assignment in enumerate(chapter_assignments, start=1):
        if not isinstance(assignment, dict):
            continue
        try:
            chapter_index = int(assignment.get("chapter_index", fallback_index) or fallback_index)
        except (TypeError, ValueError):
            chapter_index = fallback_index
        if chapter_index > 0:
            indexed[chapter_index] = assignment
    return indexed


def _resolve_published_chapter_source_file_ids(
    chapter: dict,
    *,
    chapter_index: int,
    fallback_assignment: dict | None,
    assignments_by_index: dict[int, dict],
) -> list[int]:
    """Resolve internal RawFile.id values for a published chapter.

    DocGen stores public file selection as RawFile.uid at API boundaries, but
    persisted chapter/source manifests use RawFile.id because parsed markdown
    rows and retrieval chunks are keyed by the database id.
    """

    ids = _clean_source_file_ids(chapter.get("source_file_ids"))
    if ids:
        return ids
    indexed_assignment = assignments_by_index.get(chapter_index) or {}
    ids = _clean_source_file_ids(indexed_assignment.get("source_file_ids"))
    if ids:
        return ids
    return _clean_source_file_ids((fallback_assignment or {}).get("source_file_ids"))


async def stage_knowledge_docs(
    *,
    subject: str,
    chapter_metadatas: list[dict],
    document_context: dict[str, object] | None = None,
    cover_markdown: str | None = None,
    docgen_artifacts: dict[str, Any] | None = None,
) -> StagedKnowledgeDocs:
    """Write chapter markdown into staging storage."""

    if not chapter_metadatas:
        return StagedKnowledgeDocs()

    cs = get_content_store()
    subject_scope = resolve_subject_storage_scope(subject)
    sorted_chapters = _dedupe_chapter_metadatas(
        sorted(chapter_metadatas, key=lambda item: item.get("chapter_index", 0))
    )
    built_paths: list[tuple[int, str]] = []
    write_tasks: list[asyncio.Task[None]] = []

    for index, chapter in enumerate(sorted_chapters, start=1):
        chapter_index = int(chapter.get("chapter_index", index))
        chapter_title = resolve_effective_chapter_title(chapter, chapter_index=chapter_index)
        chapter_markdown = _prepare_chapter_markdown(str(chapter.get("markdown") or ""))
        staging_key = _staging_chapter_key(subject_scope.namespace, chapter_index, chapter_title)
        write_tasks.append(asyncio.create_task(cs.write_text(staging_key, chapter_markdown)))
        built_paths.append((chapter_index, chapter_title))

    try:
        if write_tasks:
            await asyncio.gather(*write_tasks)
    except asyncio.CancelledError:
        await cancel_tasks_and_drain(write_tasks)
        raise

    merged_markdown = build_merged_markdown(
        sorted_chapters,
        document_context=document_context,
        cover_markdown=cover_markdown,
    )
    await cs.write_text(subject_scope.knowledge_build_prefix() + "merged_knowledge_base.md", merged_markdown)
    if docgen_artifacts is not None:
        await cs.write_json_raw(subject_scope.knowledge_build_prefix() + "docgen_manifest.json", docgen_artifacts)

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
    cover_markdown: str | None,
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
    subject_scope = resolve_subject_storage_scope(subject)
    sorted_chapters = _dedupe_chapter_metadatas(
        sorted(chapter_metadatas, key=lambda item: item.get("chapter_index", 0))
    )
    with managed_session() as session:
        latest_version_no = docgen_repo.get_latest_version_no(session, subject)
    resolved_version_no = max(int(version_no or 0), latest_version_no + 1)
    package_key = f"{subject}:docgen:v{resolved_version_no:04d}"
    published_at = utcnow()
    assignments_by_index = _assignments_by_chapter_index(chapter_assignments)
    resolved_docgen_artifacts: dict[str, Any] | None = None
    if docgen_artifacts is not None:
        resolved_docgen_artifacts = dict(docgen_artifacts)
        build_metadata = dict(resolved_docgen_artifacts.get("build_metadata") or {})
        build_metadata.update(
            {
                "version_no": resolved_version_no,
                "build_session_id": build_session_id or str(build_metadata.get("build_session_id") or ""),
            }
        )
        resolved_docgen_artifacts["build_metadata"] = build_metadata

    clear_current_published_knowledge_docs_files(subject)

    docs_to_create: list[KnowledgeDoc] = []
    for index, chapter in enumerate(sorted_chapters):
        chapter_index = int(chapter.get("chapter_index", index + 1))
        chapter_title = resolve_effective_chapter_title(chapter, chapter_index=chapter_index)
        chapter_markdown = _prepare_chapter_markdown(str(chapter.get("markdown") or ""))
        summary = str(chapter.get("summary") or "")
        tags = list(chapter.get("tags") or [])
        fallback_assignment = chapter_assignments[index] if index < len(chapter_assignments) else None
        source_file_ids = _resolve_published_chapter_source_file_ids(
            chapter,
            chapter_index=chapter_index,
            fallback_assignment=fallback_assignment,
            assignments_by_index=assignments_by_index,
        )
        chapter["source_file_ids"] = source_file_ids
        source_scope = dict(chapter.get("source_scope") or {})
        if source_file_ids:
            source_scope["source_file_ids"] = source_file_ids
            chapter["source_scope"] = source_scope

        final_key = _build_chapter_key(subject_scope.namespace, chapter_index, chapter_title)
        archive_key = _build_versioned_chapter_key(
            subject_scope.namespace,
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
                published_at=published_at,
                digest_mode=str(chapter.get("digest_mode") or "") or None,
                manifest_json=json.dumps(_build_chapter_manifest(chapter), ensure_ascii=False),
                source_scope_json=json.dumps(_build_source_scope(chapter), ensure_ascii=False),
            )
        )

    merged_markdown = build_merged_markdown(
        sorted_chapters,
        document_context=document_context,
        cover_markdown=cover_markdown,
    )
    run_store_sync(cs.write_text, _build_versioned_merged_key(subject_scope.namespace, resolved_version_no), merged_markdown)
    run_store_sync(cs.write_text, subject_scope.knowledge_doc_key("merged_knowledge_base.md"), merged_markdown)
    if resolved_docgen_artifacts is not None:
        versioned_manifest_key = _build_versioned_docgen_manifest_key(subject_scope.namespace, resolved_version_no)
        current_manifest_key = _build_current_docgen_manifest_key(subject_scope.namespace)
        run_store_sync(cs.write_json_raw, versioned_manifest_key, resolved_docgen_artifacts)
        run_store_sync(cs.write_json_raw, current_manifest_key, resolved_docgen_artifacts)

    with managed_session() as session:
        current_docs = docgen_repo.get_docs_by_subject(session, subject, only_current=True)
        for doc in current_docs:
            doc.is_current = False
            doc.status = "superseded"
            doc.superseded_at = published_at
            doc.updated_at = published_at
            session.add(doc)
        for doc in docs_to_create:
            session.add(doc)
        session.flush()
        update_subject_learning_context_from_docgen(
            session,
            subject=subject,
            document_context=document_context,
            chapter_metadatas=sorted_chapters,
            chapter_assignments=chapter_assignments,
            knowledge_docs=docs_to_create,
            docgen_artifacts=resolved_docgen_artifacts,
            version_no=resolved_version_no,
            build_session_id=build_session_id,
            requested_at=requested_at,
        )
        session.commit()
        created_docs: list[KnowledgeDoc] = []
        for doc in docs_to_create:
            session.refresh(doc)
            created_docs.append(doc)

    manifest = KnowledgeDocsManifest(
        updated_at=published_at,
        version_no=resolved_version_no,
        source_file_ids=sorted(
            {
                int(file_id)
                for chapter in sorted_chapters
                for file_id in _clean_source_file_ids(chapter.get("source_file_ids"))
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
    if resolved_docgen_artifacts is not None:
        manifest.docgen_manifest_key = _build_versioned_docgen_manifest_key(subject_scope.namespace, resolved_version_no)
        manifest.merge_review_report = dict(resolved_docgen_artifacts.get("merge_review_report") or {})
    # Do not mark the build completed until live docs are committed and staging is cleared,
    # otherwise `/knowledge/docs` can briefly report 100% while no readable document is available.
    write_knowledge_manifest(subject, manifest)
    run_store_sync(cs.delete_prefix, subject_scope.knowledge_build_prefix(), default=0)
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

    return [doc.id for doc in created_docs if doc.id is not None]
