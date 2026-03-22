"""Resolve-phase nodes for the digest graph workflow."""

from __future__ import annotations

from app.workflows.digest.kg.services.clusterer import ClusteredCandidate
from app.workflows.digest.kg.services.impact_analyzer import analyze_impact
from app.workflows.digest.kg.services.resolver import ResolveResult, resolve_edge, resolve_node
from app.core.database import managed_session
from app.core.embedding import aembed_texts
from app.models.knowledge_graph import EdgeRevision
from app.repositories import kg_repo
from app.utils.job_helpers import update_job_progress
from app.utils.time import utcnow
from app.workflows.digest.kg.mutations import (
    create_alias_if_new,
    create_edge_evidence,
    create_new_node,
    create_node_evidence,
    create_updated_revision,
)
from app.workflows.digest.kg.state import KGDigestState
from app.workflows.digest.kg.support import workflow_logger


async def resolve_nodes_node(state: KGDigestState) -> KGDigestState:
    """Resolve clustered candidates against existing graph nodes."""

    with managed_session() as session:
        digest_logger = workflow_logger(state)
        try:
            clustered_candidates: list[ClusteredCandidate] = state.get("clustered_candidates", [])
            subject = state["subject"]
            job_id = state["job_id"]

            candidate_name_to_resolved_node_id: dict[str, int] = {}
            cluster_id_to_resolved_node_id: dict[int, int] = {}
            new_node_ids: list[int] = []
            updated_node_ids: list[int] = []
            merged_node_ids: list[int] = []

            for cluster_index, clustered_candidate in enumerate(clustered_candidates):
                representative = clustered_candidate.representative
                embedding_text = f"{representative.name}\n{clustered_candidate.merged_summary}"
                embeddings = await aembed_texts([embedding_text])
                candidate_embedding = embeddings[0] if embeddings else []

                result: ResolveResult = await resolve_node(
                    session,
                    clustered_candidate,
                    subject,
                    candidate_embedding,
                    candidate_name_to_resolved_node_id=candidate_name_to_resolved_node_id,
                )

                if result.decision in {"exact", "alias"} and result.matched_node_id is not None:
                    node_id = result.matched_node_id
                    for member in clustered_candidate.members:
                        candidate_name_to_resolved_node_id[member.name] = node_id
                    cluster_id_to_resolved_node_id[cluster_index] = node_id

                    for chunk_id in clustered_candidate.source_chunk_ids:
                        create_node_evidence(
                            session,
                            subject=subject,
                            node_id=node_id,
                            chunk_id=chunk_id,
                            job_id=job_id,
                        )

                    for alias_name in result.new_aliases:
                        create_alias_if_new(
                            session,
                            node_id=node_id,
                            alias_name=alias_name,
                            job_id=job_id,
                        )

                    if result.is_content_update:
                        create_updated_revision(
                            session,
                            node_id=node_id,
                            clustered_candidate=clustered_candidate,
                            job_id=job_id,
                        )
                        updated_node_ids.append(node_id)

                elif result.decision == "no_match":
                    node = create_new_node(
                        session,
                        subject=subject,
                        clustered_candidate=clustered_candidate,
                        job_id=job_id,
                    )
                    node_id = node.id  # type: ignore[assignment]
                    for member in clustered_candidate.members:
                        candidate_name_to_resolved_node_id[member.name] = node_id
                    cluster_id_to_resolved_node_id[cluster_index] = node_id

                    for chunk_id in clustered_candidate.source_chunk_ids:
                        create_node_evidence(
                            session,
                            subject=subject,
                            node_id=node_id,
                            chunk_id=chunk_id,
                            job_id=job_id,
                        )
                    new_node_ids.append(node_id)

                if (cluster_index + 1) % 20 == 0:
                    progress = 50 + int(15 * (cluster_index + 1) / len(clustered_candidates))
                    update_job_progress(
                        session,
                        job_id=job_id,
                        job_type="graph",
                        progress=min(progress, 65),
                        current_step="resolve_nodes",
                    )

            update_job_progress(
                session,
                job_id=job_id,
                job_type="graph",
                progress=65,
                current_step="resolve_nodes",
            )

            kg_repo.update_digest_job(
                session,
                job_id,
                nodes_added=len(new_node_ids),
                nodes_updated=len(updated_node_ids),
                nodes_merged=len(merged_node_ids),
            )

            digest_logger.info(
                "kg_workflow_resolve_nodes_complete",
                new_nodes=len(new_node_ids),
                updated_nodes=len(updated_node_ids),
                total_resolved=len(candidate_name_to_resolved_node_id),
            )
            return {
                **state,
                "candidate_name_to_resolved_node_id": candidate_name_to_resolved_node_id,
                "cluster_id_to_resolved_node_id": cluster_id_to_resolved_node_id,
                "new_node_ids": new_node_ids,
                "updated_node_ids": updated_node_ids,
                "merged_node_ids": merged_node_ids,
            }
        except Exception as exc:
            digest_logger.error("kg_workflow_resolve_nodes_failed", error=str(exc), exc_info=True)
            return {**state, "error": f"resolve_nodes_failed: {exc}"}


async def resolve_edges_node(state: KGDigestState) -> KGDigestState:
    """Resolve candidate edges against the current graph."""

    with managed_session() as session:
        digest_logger = workflow_logger(state)
        try:
            all_candidate_edges = state.get("all_candidate_edges", [])
            subject = state["subject"]
            job_id = state["job_id"]
            candidate_name_to_resolved_node_id = state.get("candidate_name_to_resolved_node_id", {})
            candidate_name_to_cluster_id = state.get("candidate_name_to_cluster_id", {})
            cluster_id_to_resolved_node_id = state.get("cluster_id_to_resolved_node_id", {})

            new_edge_ids: list[int] = []
            updated_edge_ids: list[int] = []

            for edge_candidate, chunk_id in all_candidate_edges:
                matched_edge, is_new, confidence = resolve_edge(
                    session,
                    edge_candidate,
                    subject,
                    candidate_name_to_resolved_node_id,
                    candidate_name_to_cluster_id,
                    cluster_id_to_resolved_node_id,
                )
                if matched_edge is None:
                    continue

                if is_new:
                    matched_edge.created_by_job_id = job_id
                    edge = kg_repo.create_knowledge_edge(session, matched_edge)
                    edge_id = edge.id  # type: ignore[assignment]

                    revision = EdgeRevision(
                        edge_id=edge_id,
                        revision_no=1,
                        description=edge_candidate.description,
                        weight=edge.weight,
                        confidence=confidence,
                        revision_reason="new_evidence",
                        digest_job_id=job_id,
                        is_current=True,
                    )
                    revision = kg_repo.create_edge_revision(session, revision)
                    edge.current_revision_id = revision.id
                    edge.confidence = confidence
                    session.add(edge)
                    session.commit()

                    create_edge_evidence(
                        session,
                        subject=subject,
                        edge_id=edge_id,
                        chunk_id=chunk_id,
                        job_id=job_id,
                    )
                    new_edge_ids.append(edge_id)
                    continue

                edge_id = matched_edge.id  # type: ignore[assignment]
                create_edge_evidence(
                    session,
                    subject=subject,
                    edge_id=edge_id,
                    chunk_id=chunk_id,
                    job_id=job_id,
                )
                matched_edge.confidence = confidence
                matched_edge.updated_at = utcnow()
                session.add(matched_edge)
                session.commit()
                updated_edge_ids.append(edge_id)

            update_job_progress(
                session,
                job_id=job_id,
                job_type="graph",
                progress=75,
                current_step="resolve_edges",
            )

            kg_repo.update_digest_job(
                session,
                job_id,
                edges_added=len(new_edge_ids),
                edges_updated=len(updated_edge_ids),
            )

            digest_logger.info(
                "kg_workflow_resolve_edges_complete",
                new_edges=len(new_edge_ids),
                updated_edges=len(updated_edge_ids),
            )
            return {
                **state,
                "new_edge_ids": new_edge_ids,
                "updated_edge_ids": updated_edge_ids,
            }
        except Exception as exc:
            digest_logger.error("kg_workflow_resolve_edges_failed", error=str(exc), exc_info=True)
            return {**state, "error": f"resolve_edges_failed: {exc}"}


async def analyze_impact_node(state: KGDigestState) -> KGDigestState:
    """Compute the affected curriculum scope from graph changes."""

    with managed_session() as session:
        digest_logger = workflow_logger(state)
        try:
            impact = analyze_impact(
                session,
                state["subject"],
                new_node_ids=state.get("new_node_ids", []),
                updated_node_ids=state.get("updated_node_ids", []),
                merged_node_ids=state.get("merged_node_ids", []),
                split_node_ids=[],
            )
            update_job_progress(
                session,
                job_id=state["job_id"],
                job_type="graph",
                progress=85,
                current_step="analyze_impact",
            )
            digest_logger.info(
                "kg_workflow_impact_complete",
                changed_nodes=len(impact.changed_node_ids),
                affected_units=len(impact.affected_unit_ids),
            )
            return {**state, "impact_set": impact}
        except Exception as exc:
            digest_logger.error("kg_workflow_analyze_impact_failed", error=str(exc), exc_info=True)
            return {**state, "error": f"analyze_impact_failed: {exc}"}


__all__ = [
    "analyze_impact_node",
    "resolve_edges_node",
    "resolve_nodes_node",
]
