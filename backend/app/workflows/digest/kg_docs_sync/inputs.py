"""Knowledge-doc sync input resolvers."""

from __future__ import annotations

from dataclasses import dataclass, field
import json

from sqlmodel import Session, select

from app.repositories.knowledge.docgen_repo import get_current_published_docs
from app.shared.infra.database import managed_session
from app.shared.infra.knowledge.build_store import read_knowledge_manifest
from app.shared.infra.storage import get_content_store, run_store_sync
from app.shared.infra.tools.builtin.markdown_processing import normalize_mermaid_blocks
from app.models.knowledge_doc import KnowledgeDoc
from app.models.subject import Subject
from app.workflows.digest.common.markdown_knowledge_anchors import extract_markdown_chapter_chunks


@dataclass(slots=True)
class KnowledgeDocSyncInput:
    """Structured input consumed by kg_docs_sync."""

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


def _load_docgen_manifest(subject: str) -> dict[str, object]:
    manifest = read_knowledge_manifest(subject)
    if manifest is None or not manifest.docgen_manifest_key:
        return {}
    payload = run_store_sync(
        get_content_store().read_json_raw,
        manifest.docgen_manifest_key,
        default=None,
    )
    return dict(payload) if isinstance(payload, dict) else {}


def _chapter_context_payload(doc: KnowledgeDoc) -> dict[str, object]:
    source_scope = _load_json_dict(doc.source_scope_json)
    manifest = _load_json_dict(doc.manifest_json)
    source_file_ids = _clean_int_list(
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


def load_knowledge_doc_sync_input(subject: str) -> KnowledgeDocSyncInput:
    with managed_session() as session:
        docs = get_current_published_docs(session, subject)
        merged = _merge_doc_markdown(docs).strip()
        subject_record = session.exec(select(Subject).where(Subject.slug == subject)).first()
        document_summary_json = (
            dict(subject_record.document_summary_json)
            if subject_record is not None and isinstance(subject_record.document_summary_json, dict)
            else {}
        )
    if merged:
        doc_versions = [int(doc.version_no or doc.version or 0) for doc in docs]
        structured_context = {
            "doc_version_no": max(doc_versions or [0]),
            "docgen_manifest": _load_docgen_manifest(subject),
            "document_summary_json": document_summary_json,
            "chapters": [_chapter_context_payload(doc) for doc in docs],
        }
        return KnowledgeDocSyncInput(
            markdown=merged,
            source="database",
            structured_context=structured_context,
        )
    return KnowledgeDocSyncInput()


def load_knowledge_doc_markdown(subject: str) -> tuple[str, str]:
    sync_input = load_knowledge_doc_sync_input(subject)
    return sync_input.markdown, sync_input.source


def resolve_graph_input_paths(*, file_ids: list[int], knowledge_doc_markdown: str) -> list[str]:
    paths: list[str] = []
    if knowledge_doc_markdown.strip():
        paths.append("knowledge_doc")
    if file_ids:
        paths.append("source_files")
    return paths or ["none"]


__all__ = [
    "extract_doc_chapter_metadatas",
    "KnowledgeDocSyncInput",
    "load_knowledge_doc_sync_input",
    "load_knowledge_doc_markdown",
    "resolve_graph_input_paths",
]
