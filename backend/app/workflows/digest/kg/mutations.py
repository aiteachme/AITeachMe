"""Mutation helpers for digest graph workflow persistence."""

from __future__ import annotations

from sqlmodel import Session

from app.workflows.digest.kg.services.clusterer import ClusteredCandidate
from app.models.knowledge import DocumentChunk
from app.models.knowledge_graph import (
    EvidenceLink,
    KnowledgeAlias,
    KnowledgeNode,
    KnowledgeRevision,
)
from app.repositories import kg_repo
from app.utils.kg_helpers import normalize_name
from app.utils.time import utcnow


def create_new_node(
    session: Session,
    *,
    subject: str,
    clustered_candidate: ClusteredCandidate,
    job_id: int,
) -> KnowledgeNode:
    representative = clustered_candidate.representative
    node = KnowledgeNode(
        subject=subject,
        node_type=representative.node_type,
        canonical_name=representative.name,
        normalized_name=normalize_name(representative.name),
        status="pending",
    )
    node = kg_repo.create_knowledge_node(session, node)

    revision = KnowledgeRevision(
        node_id=node.id,  # type: ignore[arg-type]
        revision_no=1,
        title=representative.name,
        summary=clustered_candidate.merged_summary,
        body="",
        revision_reason="new_evidence",
        is_current=True,
    )
    revision = kg_repo.create_knowledge_revision(session, revision)
    node.current_revision_id = revision.id
    session.add(node)
    session.commit()

    alias = KnowledgeAlias(
        node_id=node.id,  # type: ignore[arg-type]
        alias=representative.name,
        normalized_alias=normalize_name(representative.name),
        source="llm",
        is_primary=True,
    )
    kg_repo.create_alias(session, alias)
    return node


def create_updated_revision(
    session: Session,
    *,
    node_id: int,
    clustered_candidate: ClusteredCandidate,
    job_id: int,
) -> None:
    result = kg_repo.get_node_with_current_revision(session, node_id)
    if result is None:
        return

    node, current_revision = result
    merged_summary = current_revision.summary
    if (
        clustered_candidate.merged_summary
        and clustered_candidate.merged_summary not in merged_summary
    ):
        merged_summary = f"{merged_summary}\n{clustered_candidate.merged_summary}"

    kg_repo.deactivate_old_revisions(session, node_id)
    revision = KnowledgeRevision(
        node_id=node_id,
        revision_no=current_revision.revision_no + 1,
        title=current_revision.title,
        summary=merged_summary,
        body=current_revision.body,
        revision_reason="new_evidence",
        is_current=True,
    )
    revision = kg_repo.create_knowledge_revision(session, revision)
    node.current_revision_id = revision.id
    node.updated_at = utcnow()
    session.add(node)
    session.commit()


def create_alias_if_new(
    session: Session,
    *,
    node_id: int,
    alias_name: str,
    job_id: int,
) -> None:
    normalized_alias = normalize_name(alias_name)
    existing_aliases = kg_repo.list_aliases_by_node(session, node_id)
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
    )


def create_node_evidence(
    session: Session,
    *,
    subject: str,
    node_id: int,
    chunk_id: int,
    job_id: int,
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
    )


def create_edge_evidence(
    session: Session,
    *,
    subject: str,
    edge_id: int,
    chunk_id: int,
    job_id: int,
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
    )


__all__ = [
    "create_alias_if_new",
    "create_edge_evidence",
    "create_new_node",
    "create_node_evidence",
    "create_updated_revision",
]
