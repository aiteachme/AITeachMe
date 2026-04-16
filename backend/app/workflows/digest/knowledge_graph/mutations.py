"""Mutation helpers for digest graph workflow persistence."""

from __future__ import annotations

from sqlmodel import Session

from app.workflows.digest.knowledge_graph.lib.clusterer import ClusteredCandidate
from app.models.knowledge import DocumentChunk
from app.models.knowledge_graph import (
    EvidenceLink,
    KnowledgeAlias,
    KnowledgeUnit,
    KnowledgeRevision,
)
from app.repositories import kg_repo
from app.utils.kg_helpers import normalize_name
from app.utils.time import utcnow
from app.models.kg_taxonomy import (
    normalize_knowledge_unit_type,
    normalize_type_source,
)


def _iter_taxonomy_hints(clustered_candidate: ClusteredCandidate | None) -> list[str]:
    if clustered_candidate is None:
        return []
    hints: list[str] = []
    for member in clustered_candidate.members or [clustered_candidate.representative]:
        hint = (member.taxonomy_hint or "").strip()
        if hint:
            hints.append(hint)
    return list(dict.fromkeys(hints))


def create_new_knowledge_unit(
    session: Session,
    *,
    subject: str,
    clustered_candidate: ClusteredCandidate,
    job_id: int,
    auto_commit: bool = True,
) -> KnowledgeUnit:
    representative = clustered_candidate.representative
    node_type = normalize_knowledge_unit_type(representative.node_type)
    knowledge_unit = KnowledgeUnit(
        subject=subject,
        node_type=node_type,
        canonical_name=representative.name,
        normalized_name=normalize_name(representative.name),
        status="pending",
        type_confidence=getattr(representative, "type_confidence", 1.0),
        type_source=normalize_type_source(getattr(representative, "type_source", None)),
    )
    knowledge_unit = kg_repo.create_knowledge_unit(session, knowledge_unit, auto_commit=auto_commit)

    revision = KnowledgeRevision(
        node_id=knowledge_unit.id,  # type: ignore[arg-type]
        revision_no=1,
        title=representative.name,
        summary=clustered_candidate.merged_summary,
        body="",
        revision_reason="new_evidence",
        is_current=True,
    )
    kg_repo.create_knowledge_revision(session, revision, auto_commit=auto_commit)
    if auto_commit:
        session.refresh(knowledge_unit)

    alias = KnowledgeAlias(
        node_id=knowledge_unit.id,  # type: ignore[arg-type]
        alias=representative.name,
        normalized_alias=normalize_name(representative.name),
        source="llm",
        is_primary=True,
    )
    kg_repo.create_alias(session, alias, auto_commit=auto_commit)
    return knowledge_unit


def create_updated_revision(
    session: Session,
    *,
    node_id: int,
    clustered_candidate: ClusteredCandidate,
    job_id: int,
    auto_commit: bool = True,
) -> None:
    result = kg_repo.get_knowledge_unit_with_current_revision(session, node_id)
    if result is None:
        return

    node, current_revision = result
    merged_summary = current_revision.summary
    if (
        clustered_candidate.merged_summary
        and clustered_candidate.merged_summary not in merged_summary
    ):
        merged_summary = f"{merged_summary}\n{clustered_candidate.merged_summary}"

    kg_repo.deactivate_old_knowledge_unit_revisions(session, node_id)
    revision = KnowledgeRevision(
        node_id=node_id,
        revision_no=current_revision.revision_no + 1,
        title=current_revision.title,
        summary=merged_summary,
        body=current_revision.body,
        revision_reason="new_evidence",
        is_current=True,
    )
    kg_repo.create_knowledge_revision(session, revision, auto_commit=auto_commit)
    node.updated_at = utcnow()
    session.add(node)
    if auto_commit:
        session.commit()


def create_alias_if_new(
    session: Session,
    *,
    node_id: int,
    alias_name: str,
    job_id: int,
    auto_commit: bool = True,
) -> None:
    normalized_alias = normalize_name(alias_name)
    existing_aliases = kg_repo.list_aliases_by_knowledge_unit(session, node_id)
    if any(alias.normalized_alias == normalized_alias for alias in existing_aliases):
        return

    kg_repo.create_alias(
        session,
        KnowledgeAlias(
            node_id=node_id,
            alias=alias_name,
            normalized_alias=normalized_alias,
            source="llm",
            is_primary=False,
        ),
        auto_commit=auto_commit,
    )


def create_node_evidence(
    session: Session,
    *,
    subject: str,
    node_id: int,
    chunk_id: int,
    job_id: int,
    clustered_candidate: ClusteredCandidate | None = None,
    auto_commit: bool = True,
) -> None:
    chunk = session.get(DocumentChunk, chunk_id)
    if chunk is None:
        return

    kg_repo.create_evidence_link(
        session,
        EvidenceLink(
            subject=subject,
            entity_type="node",
            entity_id=node_id,
            document_id=chunk.document_id,
            chunk_id=chunk_id,
            evidence_role="supports",
            extraction_method="llm",
            field_scope="summary",
        ),
        auto_commit=auto_commit,
    )
    for taxonomy_hint in _iter_taxonomy_hints(clustered_candidate):
        kg_repo.create_evidence_link(
            session,
            EvidenceLink(
                subject=subject,
                entity_type="node",
                entity_id=node_id,
                document_id=chunk.document_id,
                chunk_id=chunk_id,
                quote_text=taxonomy_hint,
                evidence_role="taxonomy_hint",
                extraction_method="llm",
                field_scope="taxonomy_hint",
            ),
            auto_commit=auto_commit,
        )


def create_edge_evidence(
    session: Session,
    *,
    subject: str,
    edge_id: int,
    chunk_id: int,
    job_id: int,
    auto_commit: bool = True,
) -> None:
    chunk = session.get(DocumentChunk, chunk_id)
    if chunk is None:
        return

    kg_repo.create_evidence_link(
        session,
        EvidenceLink(
            subject=subject,
            entity_type="edge",
            entity_id=edge_id,
            document_id=chunk.document_id,
            chunk_id=chunk_id,
            evidence_role="supports",
            extraction_method="llm",
            field_scope="edge_description",
        ),
        auto_commit=auto_commit,
    )


__all__ = [
    "create_alias_if_new",
    "create_edge_evidence",
    "create_new_knowledge_unit",
    "create_node_evidence",
    "create_updated_revision",
]
