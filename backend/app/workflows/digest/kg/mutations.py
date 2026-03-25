"""Mutation helpers for digest graph workflow persistence."""

from __future__ import annotations

from sqlmodel import Session, select

from app.models import KnowledgeAlias, KnowledgeEvidence, KnowledgeNode, RetrievalChunk, Subject
from app.repositories.knowledge import kg_repo
from app.utils.kg_helpers import normalize_name
from app.utils.time import utcnow
from app.workflows.digest.kg.services.clusterer import ClusteredCandidate


def _resolve_subject_owner(session: Session, subject: str) -> Subject:
    subject_row = session.exec(select(Subject).where(Subject.slug == subject)).first()
    if subject_row is None or subject_row.id is None:
        raise ValueError(f"Unknown subject `{subject}`")
    return subject_row


def create_new_node(
    session: Session,
    *,
    subject: str,
    clustered_candidate: ClusteredCandidate,
    job_id: int,
) -> KnowledgeNode:
    del job_id
    representative = clustered_candidate.representative
    subject_row = _resolve_subject_owner(session, subject)
    node = KnowledgeNode(
        user_id=subject_row.user_id,
        subject_id=int(subject_row.id),
        node_type=representative.node_type,
        canonical_name=representative.name,
        normalized_name=normalize_name(representative.name),
        summary=clustered_candidate.merged_summary,
        body=clustered_candidate.merged_summary,
        status="pending",
        confidence=0.8,
    )
    node = kg_repo.create_knowledge_node(session, node)
    kg_repo.create_alias(
        session,
        KnowledgeAlias(
            node_id=int(node.id or 0),
            alias=representative.name,
            normalized_alias=normalize_name(representative.name),
            source="llm",
            confidence=0.9,
            is_primary=True,
            status="pending",
        ),
    )
    return node


def create_updated_revision(
    session: Session,
    *,
    node_id: int,
    clustered_candidate: ClusteredCandidate,
    job_id: int,
) -> None:
    del job_id
    node = session.get(KnowledgeNode, node_id)
    if node is None:
        return

    merged_summary = (node.summary or "").strip()
    candidate_summary = clustered_candidate.merged_summary.strip()
    if candidate_summary and candidate_summary not in merged_summary:
        node.summary = "\n".join(part for part in [merged_summary, candidate_summary] if part).strip()
        node.body = "\n\n".join(part for part in [node.body.strip(), candidate_summary] if part).strip()
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
    del job_id
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
            confidence=0.8,
            is_primary=False,
            status="pending",
        ),
    )


def _build_quote_text(chunk: RetrievalChunk) -> str:
    text = chunk.content.replace("\n", " ").strip()
    return text[:240]


def create_node_evidence(
    session: Session,
    *,
    subject: str,
    node_id: int,
    chunk_id: int,
    job_id: int,
) -> None:
    del subject, job_id
    chunk = session.get(RetrievalChunk, chunk_id)
    if chunk is None:
        return

    kg_repo.create_knowledge_evidence(
        session,
        KnowledgeEvidence(
            user_id=chunk.user_id,
            subject_id=chunk.subject_id,
            node_id=node_id,
            edge_id=None,
            retrieval_chunk_id=chunk_id,
            quote_text=_build_quote_text(chunk),
            evidence_role="support",
            extraction_method="llm",
            field_scope="summary",
            confidence=0.8,
            is_active=False,
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
    del subject, job_id
    chunk = session.get(RetrievalChunk, chunk_id)
    if chunk is None:
        return

    kg_repo.create_knowledge_evidence(
        session,
        KnowledgeEvidence(
            user_id=chunk.user_id,
            subject_id=chunk.subject_id,
            node_id=None,
            edge_id=edge_id,
            retrieval_chunk_id=chunk_id,
            quote_text=_build_quote_text(chunk),
            evidence_role="support",
            extraction_method="llm",
            field_scope="edge_description",
            confidence=0.75,
            is_active=False,
        ),
    )


__all__ = [
    "create_alias_if_new",
    "create_edge_evidence",
    "create_new_node",
    "create_node_evidence",
    "create_updated_revision",
]
