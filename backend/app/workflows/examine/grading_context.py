"""Grading knowledge context builder."""

from __future__ import annotations

from sqlmodel import Session

from app.repositories.knowledge import curriculum_repo, kg_repo
from app.workflows.examine.context_helpers import (
    _extract_doc_excerpt,
    read_knowledge_doc_text,
    truncate_text,
)
from app.workflows.examine.unit_context import NodeExamContext, _resolve_node_content


def build_grading_knowledge_context(
    session: Session,
    *,
    subject: str,
    teaching_unit_id: int | None = None,
    node_ids: list[int] | None = None,
    max_chars: int = 1800,
    knowledge_doc_text: str | None = None,
) -> str:
    unique_node_ids = [node_id for node_id in dict.fromkeys(node_ids or []) if int(node_id) > 0]
    unit = curriculum_repo.get_teaching_unit_by_id(session, teaching_unit_id) if teaching_unit_id else None

    node_contexts: list[NodeExamContext] = []
    for node_id in unique_node_ids[:6]:
        node, summary, body = _resolve_node_content(session, node_id)
        if node is None:
            continue
        node_contexts.append(
            NodeExamContext(
                node_id=node_id,
                node_name=node.canonical_name,
                summary=summary,
                body=body,
                role="primary",
                coverage_weight=1.0,
            )
        )

    search_terms = [subject]
    if unit is not None:
        search_terms.extend([unit.canonical_name, unit.title])
    search_terms.extend(item.node_name for item in node_contexts)
    doc_excerpt = _extract_doc_excerpt(
        knowledge_doc_text if knowledge_doc_text is not None else read_knowledge_doc_text(subject),
        search_terms,
        max_chars=max_chars // 2,
    )

    parts: list[str] = []
    if unit is not None:
        parts.append(f"Teaching unit: {unit.canonical_name}")
        if unit.summary:
            parts.append("Unit summary:\n" + truncate_text(unit.summary, max_chars=260))
        if unit.body_markdown:
            parts.append("Unit body:\n" + truncate_text(unit.body_markdown, max_chars=360))

    if node_contexts:
        node_lines = [
            f"- {item.node_name}: {truncate_text(item.content, max_chars=260)}"
            for item in node_contexts
            if item.content.strip()
        ]
        if node_lines:
            parts.append("Knowledge anchors:\n" + "\n".join(node_lines))

    if doc_excerpt:
        parts.append("Knowledge document excerpt:\n" + truncate_text(doc_excerpt, max_chars=max_chars // 2))

    return truncate_text("\n\n".join(part for part in parts if part.strip()), max_chars=max_chars)


__all__ = [
    "build_grading_knowledge_context",
]
