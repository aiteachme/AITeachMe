"""Docs-sync prepare node."""

from __future__ import annotations

import re

from app.workflows.digest.kg_doc_sync.nodes.node_state import with_node_error, with_node_metrics
from app.workflows.digest.kg_doc_sync.state import DocsSyncState


def _safe_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _structured_context_metrics(structured_context: dict[str, object]) -> dict[str, object]:
    chapters = structured_context.get("chapters")
    docgen_manifest = structured_context.get("docgen_manifest")
    document_summary = structured_context.get("document_summary_json")
    return {
        "chapter_context_count": len(chapters) if isinstance(chapters, list) else 0,
        "doc_version_no": _safe_int(structured_context.get("doc_version_no")),
        "has_docgen_manifest": isinstance(docgen_manifest, dict) and bool(docgen_manifest),
        "has_document_summary": isinstance(document_summary, dict) and bool(document_summary),
    }


def _markdown_metrics(markdown: str) -> dict[str, object]:
    lines = markdown.splitlines()
    return {
        "markdown_chars": len(markdown),
        "markdown_lines": len(lines),
        "heading_count": sum(1 for line in lines if line.lstrip().startswith("#")),
        "knowledge_anchor_count": len(re.findall(r"<!--\s*ATM[-_]KU\s*:", markdown, flags=re.IGNORECASE)),
    }


def prepare_node(state: DocsSyncState) -> DocsSyncState:
    """Validate the published knowledge doc before opening a graph sync run."""

    subject = str(state.get("subject") or "").strip()
    markdown = str(state.get("markdown") or "")
    structured_context = dict(state.get("structured_context") or {})
    metrics = {
        "ok": False,
        **_markdown_metrics(markdown),
        **_structured_context_metrics(structured_context),
    }
    if not subject:
        return with_node_error(state, "prepare", "docs_sync_missing_subject", metrics=metrics)
    if not markdown.strip():
        return with_node_error(state, "prepare", "docs_sync_missing_markdown", metrics=metrics)
    return with_node_metrics(
        state,
        "prepare",
        {
            **metrics,
            "ok": True,
            "subject": subject,
        },
        subject=subject,
        structured_context=structured_context,
        error=None,
    )


__all__ = ["prepare_node"]
