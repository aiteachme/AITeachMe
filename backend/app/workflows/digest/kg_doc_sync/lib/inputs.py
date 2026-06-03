"""Knowledge-doc sync input resolvers."""

from __future__ import annotations

from dataclasses import dataclass, field
import json

from sqlmodel import Session, select

from app.repositories.knowledge.docgen_repo import get_current_published_docs
from app.shared.infra.database import managed_session
from app.shared.infra.knowledge.build_store import read_knowledge_manifest
from app.shared.infra.storage import CourseStorageScope, get_content_store, run_store_sync
from app.shared.infra.tools.builtin.markdown_processing import normalize_mermaid_blocks
from app.models.knowledge_doc import KnowledgeDoc
from app.models.course import Course
from app.workflows.digest.common.markdown_knowledge_anchors import extract_markdown_chapter_chunks


@dataclass(slots=True)
class KnowledgeDocSyncInput:
    """Structured input consumed by kg_doc_sync."""

    markdown: str = ""
    source: str = "none"
    structured_context: dict[str, object] = field(default_factory=dict)


def _load_json_dict(raw: str | None) -> dict[str, object]:
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _load_json_list(raw: str | None) -> list[object]:
    try:
        payload = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return list(payload) if isinstance(payload, list) else []


def _safe_int(value: object, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clean_int_list(value: object) -> list[int]:
    items = value if isinstance(value, list) else ([] if value is None else [value])
    cleaned: list[int] = []
    seen: set[int] = set()
    for item in items:
        try:
            parsed = int(item)
        except (TypeError, ValueError):
            continue
        if parsed <= 0 or parsed in seen:
            continue
        seen.add(parsed)
        cleaned.append(parsed)
    return cleaned


def _clean_string_list(value: object) -> list[str]:
    items = value if isinstance(value, list) else ([] if value is None else [value])
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def extract_doc_chapter_metadatas(markdown: str) -> list[dict[str, object]]:
    chapters: list[dict[str, object]] = []
    for chunk in extract_markdown_chapter_chunks(markdown)[:60]:
        summary = str(chunk.summary or "").strip()
        if not summary:
            summary = " ".join(
                segment.strip()
                for segment in str(chunk.body_markdown or "").splitlines()
                if segment.strip() and not segment.strip().startswith("#")
            ).strip()
        if len(summary) > 1200:
            summary = summary[:1200].rstrip() + "..."
        title = str(chunk.title or "").strip() or f"Chapter {len(chapters) + 1}"
        chapters.append(
            {
                "chapter_index": len(chapters) + 1,
                "title": title,
                "summary": summary,
                "research_summary": "",
                "tags": [],
                "source_file_ids": [],
            }
        )
    return chapters


def _merge_doc_markdown(docs: list[KnowledgeDoc]) -> str:
    parts = [
        normalize_mermaid_blocks(
            str(doc.markdown_content or doc.content_markdown or "").strip()
        )
        for doc in docs
        if str(doc.markdown_content or doc.content_markdown or "").strip()
    ]
    if not parts:
        return ""
    return ("\n\n---\n\n".join(parts)).strip()


def _load_docgen_manifest(
    course_id: str,
    *,
    course_scope: CourseStorageScope | None = None,
) -> dict[str, object]:
    manifest = read_knowledge_manifest(course_id, course_scope=course_scope)
    if manifest is None or not manifest.docgen_manifest_key:
        return {}
    payload = run_store_sync(
        get_content_store().read_json_raw,
        manifest.docgen_manifest_key,
        default=None,
    )
    return dict(payload) if isinstance(payload, dict) else {}


def _load_docgen_manifest_for_scope(
    course_id: str,
    course_scope: CourseStorageScope | None,
) -> dict[str, object]:
    if course_scope is None:
        return _load_docgen_manifest(course_id)
    return _load_docgen_manifest(course_id, course_scope=course_scope)


def _chapter_context_payload(doc: KnowledgeDoc) -> dict[str, object]:
    source_scope = _load_json_dict(doc.source_scope_json)
    manifest = _load_json_dict(doc.manifest_json)
    source_file_ids = _clean_string_list(
        _load_json_list(doc.source_file_ids)
        or source_scope.get("source_file_ids")
        or manifest.get("source_file_ids")
    )
    return {
        "knowledge_document_id": doc.id,
        "chapter_index": int(doc.chapter_index or 0),
        "title": doc.title,
        "summary": doc.summary,
        "source_file_ids": source_file_ids,
        "source_scope": source_scope,
        "manifest": manifest,
    }


def _chapter_context_from_docgen_state(
    chapter: dict[str, object],
    *,
    knowledge_document_id: int | None,
) -> dict[str, object]:
    source_scope = dict(chapter.get("source_scope") or {}) if isinstance(chapter.get("source_scope"), dict) else {}
    manifest = dict(chapter.get("manifest") or {}) if isinstance(chapter.get("manifest"), dict) else {}
    source_file_ids = _clean_string_list(
        chapter.get("source_file_ids")
        or source_scope.get("source_file_ids")
        or manifest.get("source_file_ids")
    )
    return {
        "knowledge_document_id": knowledge_document_id,
        "chapter_index": _safe_int(chapter.get("chapter_index")),
        "title": str(chapter.get("title") or chapter.get("resolved_title") or "").strip(),
        "summary": str(chapter.get("summary") or "").strip(),
        "source_file_ids": source_file_ids,
        "source_scope": source_scope,
        "manifest": manifest,
    }


def build_knowledge_doc_sync_input_from_docgen_state(
    course_id: str,
    docgen_state: dict[str, object] | None,
    *,
    course_scope: CourseStorageScope | None = None,
    document_summary_json: dict[str, object] | None = None,
) -> KnowledgeDocSyncInput | None:
    """Build graph-sync input directly from the just-finished DocGen state."""

    state = dict(docgen_state or {})
    markdown = str(state.get("merged_markdown") or state.get("enriched_markdown") or "").strip()
    if not markdown:
        return None

    chapter_metadatas = [
        item
        for item in list(state.get("chapter_metadatas") or [])
        if isinstance(item, dict)
    ]
    doc_ids = _clean_int_list(state.get("doc_ids"))
    manifest = _load_docgen_manifest_for_scope(course_id, course_scope)
    manifest_build_metadata = (
        dict(manifest.get("build_metadata"))
        if isinstance(manifest.get("build_metadata"), dict)
        else {}
    )
    manifest_version_no = _safe_int(manifest_build_metadata.get("version_no"))
    manifest_record = (
        read_knowledge_manifest(course_id, course_scope=course_scope)
        if manifest_version_no <= 0
        else None
    )
    doc_version_no = int(
        manifest_version_no
        or (manifest_record.version_no if manifest_record is not None else 0)
        or 0
    )
    structured_context = {
        "doc_version_no": doc_version_no,
        "docgen_manifest": manifest,
        "document_summary_json": document_summary_json
        if document_summary_json is not None
        else _load_course_document_summary(course_id),
        "chapters": [
            _chapter_context_from_docgen_state(
                chapter,
                knowledge_document_id=doc_ids[index] if index < len(doc_ids) else None,
            )
            for index, chapter in enumerate(
                sorted(chapter_metadatas, key=lambda item: _safe_int(item.get("chapter_index")))
            )
        ],
    }
    return KnowledgeDocSyncInput(
        markdown=markdown,
        source="docgen_state",
        structured_context=structured_context,
    )


def _read_course_document_summary(session: Session, course_id: str) -> dict[str, object]:
    course_record = session.exec(select(Course).where(Course.id == course_id)).first()
    return (
        dict(course_record.document_summary_json)
        if course_record is not None and isinstance(course_record.document_summary_json, dict)
        else {}
    )


def _load_course_document_summary(course_id: str) -> dict[str, object]:
    with managed_session() as session:
        return _read_course_document_summary(session, course_id)


def load_knowledge_doc_sync_input(
    course_id: str,
    *,
    session: Session | None = None,
    course_scope: CourseStorageScope | None = None,
) -> KnowledgeDocSyncInput:
    if session is None:
        with managed_session() as managed:
            return load_knowledge_doc_sync_input(
                course_id,
                session=managed,
                course_scope=course_scope,
            )

    docs = get_current_published_docs(session, course_id)
    merged = _merge_doc_markdown(docs).strip()
    document_summary_json = _read_course_document_summary(session, course_id)
    if merged:
        doc_versions = [int(doc.version_no or doc.version or 0) for doc in docs]
        structured_context = {
            "doc_version_no": max(doc_versions or [0]),
            "docgen_manifest": _load_docgen_manifest_for_scope(course_id, course_scope),
            "document_summary_json": document_summary_json,
            "chapters": [_chapter_context_payload(doc) for doc in docs],
        }
        return KnowledgeDocSyncInput(
            markdown=merged,
            source="database",
            structured_context=structured_context,
        )
    return KnowledgeDocSyncInput()


def load_knowledge_doc_markdown(course_id: str) -> tuple[str, str]:
    sync_input = load_knowledge_doc_sync_input(course_id)
    return sync_input.markdown, sync_input.source


def resolve_graph_input_paths(*, file_ids: list[str], knowledge_doc_markdown: str) -> list[str]:
    paths: list[str] = []
    if knowledge_doc_markdown.strip():
        paths.append("knowledge_doc")
    if file_ids:
        paths.append("source_files")
    return paths or ["none"]


__all__ = [
    "build_knowledge_doc_sync_input_from_docgen_state",
    "extract_doc_chapter_metadatas",
    "KnowledgeDocSyncInput",
    "load_knowledge_doc_sync_input",
    "load_knowledge_doc_markdown",
    "resolve_graph_input_paths",
]
