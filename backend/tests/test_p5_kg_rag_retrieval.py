from __future__ import annotations

import asyncio

from sqlmodel import Session

from app.models import RawFile, RetrievalChunk
from app.models.knowledge_relation import EvidenceLink, KnowledgeEdge
from app.models.knowledge_unit import KnowledgeUnit
from app.models.profile import UserKnowledgeState
from app.repositories import knowledge_relation_repo, profile_repo
from app.repositories.knowledge import knowledge_repo, knowledge_unit_repo
from app.workflows.interact.chat.lib.retrieval import retrieve_context


def _unit(session: Session, *, subject: str, name: str, summary: str = "") -> KnowledgeUnit:
    unit = knowledge_unit_repo.create_knowledge_unit(
        session,
        KnowledgeUnit(
            subject=subject,
            node_type="concept",
            canonical_name=name,
            normalized_name=name.casefold().replace(" ", "_"),
            summary=summary or name,
            body_markdown=f"## {name}\n\n{summary or name}",
            status="active",
        ),
    )
    assert unit.id is not None
    return unit


def test_p5_retrieval_uses_knowledge_unit_graph_before_vector(session: Session) -> None:
    subject = "math"
    prerequisite = _unit(session, subject=subject, name="Function", summary="mapping between sets")
    target = _unit(session, subject=subject, name="Linear Function", summary="constant rate of change")
    edge = knowledge_relation_repo.create_knowledge_edge(
        session,
        KnowledgeEdge(
            subject=subject,
            source_node_id=prerequisite.id or 0,
            target_node_id=target.id or 0,
            edge_type="prerequisite",
            status="active",
        ),
    )
    assert edge.id is not None

    document = knowledge_repo.bulk_create_documents(
        session,
        [
            RawFile(
                uid="doc-1",
                subject=subject,
                filename="linear.md",
                filetype="md",
                file_path="linear.md",
            )
        ],
    )[0]
    chunk = knowledge_repo.bulk_create_chunks(
        session,
        [
            RetrievalChunk(
                subject=subject,
                document_id=document.id or 0,
                title="Linear Function",
                level=2,
                header_path="Functions > Linear Function",
                chunk_index=1,
                digest_chunk_uid="linear-function",
                content="A linear function has a constant rate of change.",
            )
        ],
    )[0]
    knowledge_relation_repo.create_evidence_link(
        session,
        EvidenceLink(
            subject=subject,
            entity_type="node",
            entity_id=target.id or 0,
            document_id=document.id or 0,
            chunk_id=chunk.id or 0,
            quote_text="constant rate of change",
            evidence_role="definition",
            field_scope="summary",
            confidence=0.9,
        ),
    )
    profile_repo.upsert_knowledge_state(
        session,
        state=UserKnowledgeState(
            user_id="local",
            subject=subject,
            knowledge_node_id=target.id,
            mastery_score=0.3,
        ),
    )

    results = asyncio.run(
        retrieve_context(
            session=session,
            query="How does a Linear Function work?",
            subject=subject,
            top_k=4,
            similarity_threshold=0.2,
            user_id="local",
        )
    )

    assert results
    target_context = next(item for item in results if item.knowledge_unit_id == target.id)
    assert target_context.retrieval_source == "knowledge_unit"
    assert target_context.chunk_id == chunk.id
    assert target_context.evidence_quote == "constant rate of change"
    assert target_context.mastery_score == 0.3
    assert "constant rate" in target_context.content
    assert any(item.relation_path and "prerequisite" in item.relation_path for item in results)
    context_payload = target_context.to_context_item()
    assert context_payload.knowledge_unit_name == "Linear Function"
    assert context_payload.retrieval_source == "knowledge_unit"
