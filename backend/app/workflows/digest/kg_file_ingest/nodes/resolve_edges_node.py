"""Knowledge graph resolve-edges node."""


from __future__ import annotations

import json
from dataclasses import dataclass, field
from time import perf_counter

from sqlmodel import select

from app.shared.infra.database import managed_session
from app.shared.infra.embedding import aembed_texts
from app.models.knowledge_relation import EdgeRevision, KnowledgeEdge
from app.models.knowledge_unit import KnowledgeUnit
from app.repositories import knowledge_relation_repo, knowledge_build_repo
from app.utils.job_helpers import update_job_progress
from app.utils.knowledge_helpers import normalize_name
from app.utils.time import utcnow
from app.workflows.digest.kg_file_ingest.mutations import (
    create_alias_if_new,
    create_edge_evidence,
    create_node_evidence,
    create_updated_revision,
)
from app.workflows.digest.kg_file_ingest.lib.candidate_identity import (
    build_candidate_name_key,
    candidate_lookup_keys,
    normalize_scope_name,
)
from app.workflows.digest.kg_file_ingest.lib.embedding_cache import (
    compute_embedding_text_hash,
    load_subject_embedding_cache,
    write_subject_embedding_cache,
)
from app.workflows.digest.kg_file_ingest.lib.impact_analyzer import analyze_impact
from app.workflows.digest.kg_file_ingest.lib.resolver import (
    ResolveResult,
    compute_edge_confidence,
    resolve_edge,
)
from app.workflows.digest.kg_file_ingest.state import KnowledgeDigestState
from app.workflows.digest.kg_file_ingest.lib.support import workflow_logger

async def resolve_edges_node(state: KnowledgeDigestState) -> KnowledgeDigestState:
    """Resolve candidate edges against the current graph."""

    with managed_session() as session:
        digest_logger = workflow_logger(state)
        try:
            all_candidate_edges = state.get("all_candidate_edges", [])
            subject = state["subject"]
            job_id = state["job_id"]
            candidate_lookup_to_resolved_node_id = state.get("candidate_lookup_to_resolved_node_id", {})
            candidate_lookup_to_cluster_id = state.get("candidate_lookup_to_cluster_id", {})
            cluster_id_to_resolved_node_id = state.get("cluster_id_to_resolved_node_id", {})
            new_edge_ids: list[int] = []
            updated_edge_ids: list[int] = []
            pending_write_count = 0
            persist_started_at = perf_counter()
            unresolved_endpoint_count = 0

            def _commit_pending_writes() -> None:
                nonlocal pending_write_count
                if pending_write_count <= 0:
                    return
                session.commit()
                pending_write_count = 0

            for edge_candidate, chunk_id in all_candidate_edges:
                matched_edge, is_new, confidence = resolve_edge(
                    session,
                    edge_candidate,
                    subject,
                    candidate_lookup_to_resolved_node_id,
                    candidate_lookup_to_cluster_id,
                    cluster_id_to_resolved_node_id,
                )
                if matched_edge is None:
                    unresolved_endpoint_count += 1
                    continue

                if is_new:
                    edge = knowledge_relation_repo.create_knowledge_edge(session, matched_edge, auto_commit=False)
                    edge_id = edge.id
                    if edge_id is None:
                        continue
                    knowledge_relation_repo.create_edge_revision(
                        session,
                        EdgeRevision(
                            edge_id=edge_id,
                            revision_no=1,
                            description=edge_candidate.description,
                            weight=edge.weight,
                            confidence=confidence,
                            revision_reason="new_evidence",
                            is_current=True,
                        ),
                        auto_commit=False,
                    )
                    edge.current_revision_id = edge_id
                    edge.confidence = confidence
                    edge.updated_at = utcnow()
                    session.add(edge)
                    create_edge_evidence(
                        session,
                        subject=subject,
                        edge_id=edge_id,
                        chunk_id=chunk_id,
                        job_id=job_id,
                        auto_commit=False,
                    )
                    pending_write_count += 3
                    new_edge_ids.append(edge_id)
                else:
                    edge_id = matched_edge.id
                    if edge_id is None:
                        continue
                    create_edge_evidence(
                        session,
                        subject=subject,
                        edge_id=edge_id,
                        chunk_id=chunk_id,
                        job_id=job_id,
                        auto_commit=False,
                    )
                    active_evidence_count = knowledge_relation_repo.count_active_evidence(session, "edge", edge_id)
                    matched_edge.confidence = compute_edge_confidence(active_evidence_count)
                    matched_edge.updated_at = utcnow()
                    session.add(matched_edge)
                    pending_write_count += 2
                    updated_edge_ids.append(edge_id)

                if (len(new_edge_ids) + len(updated_edge_ids)) % 25 == 0:
                    _commit_pending_writes()

            _commit_pending_writes()
            edge_persist_ms = int((perf_counter() - persist_started_at) * 1000)
            update_job_progress(
                session,
                job_id=job_id,
                job_type="graph",
                progress=75,
                current_step="resolve_edges",
                subject=subject,
            )
            knowledge_build_repo.update_digest_job(
                session,
                job_id,
                subject=subject,
                edges_added=len(new_edge_ids),
                edges_updated=len(updated_edge_ids),
            )
            digest_logger.info(
                "knowledge_workflow_resolve_edges_complete",
                new_edges=len(new_edge_ids),
                updated_edges=len(updated_edge_ids),
            )
            return {
                **state,
                "new_edge_ids": new_edge_ids,
                "updated_edge_ids": updated_edge_ids,
                "edge_persist_ms": edge_persist_ms,
                "unresolved_endpoint_count": unresolved_endpoint_count,
            }
        except Exception as exc:
            digest_logger.error("knowledge_workflow_resolve_edges_failed", error=str(exc), exc_info=True)
            return {**state, "error": f"resolve_edges_failed: {exc}"}

__all__ = ["resolve_edges_node"]



