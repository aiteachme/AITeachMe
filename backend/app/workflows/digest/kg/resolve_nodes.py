"""Resolve and impact-analysis nodes for the graph lane."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlmodel import select

from app.core.database import managed_session
from app.core.embedding import aembed_texts
from app.models import KnowledgeEdge, KnowledgeNode, Subject
from app.repositories.knowledge import kg_repo
from app.utils.job_helpers import update_job_progress
from app.utils.kg_helpers import normalize_name
from app.utils.time import utcnow
from app.workflows.digest.kg.mutations import (
    create_alias_if_new,
    create_edge_evidence,
    create_new_node,
    create_node_evidence,
    create_updated_revision,
)
from app.workflows.digest.kg.services.impact_analyzer import analyze_impact
from app.workflows.digest.kg.state import KGDigestState
from app.workflows.digest.kg.support import workflow_logger

_PRIMARY_NODE_TYPES = {"Topic", "Concept", "Method"}
_SECONDARY_NODE_TYPES = {"Definition", "Example"}
_PRIMARY_SIMILARITY_THRESHOLD = 0.80
_SECONDARY_SIMILARITY_THRESHOLD = 0.86


@dataclass(slots=True)
class ExistingNodeRecord:
    node: KnowledgeNode
    summary: str
    embedding: list[float]


@dataclass(slots=True)
class ResolutionIndex:
    subject: str
    normalized_map: dict[tuple[str, str], ExistingNodeRecord] = field(default_factory=dict)
    alias_map: dict[tuple[str, str], ExistingNodeRecord] = field(default_factory=dict)
    records_by_type: dict[str, list[ExistingNodeRecord]] = field(default_factory=dict)
    children_by_parent: dict[int, dict[str, list[ExistingNodeRecord]]] = field(default_factory=dict)


@dataclass(slots=True)
class ResolveResult:
    decision: str
    matched_node_id: int | None = None
    is_content_update: bool = False
    new_aliases: list[str] = field(default_factory=list)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _has_content_update(candidate_summary: str, existing_summary: str) -> bool:
    if not candidate_summary.strip():
        return False
    if not existing_summary.strip():
        return True
    existing_chars = set(existing_summary)
    new_chars = sum(1 for char in candidate_summary if char not in existing_chars)
    return new_chars > len(candidate_summary) * 0.3


async def _build_resolution_index(subject: str) -> ResolutionIndex:
    with managed_session() as session:
        nodes, _ = kg_repo.list_nodes_by_subject(
            session,
            subject,
            status=None,
            limit=2000,
            offset=0,
        )
        nodes = [node for node in nodes if node.status in {"active", "pending"}]
        if not nodes:
            return ResolutionIndex(subject=subject)

        node_ids = [int(node.id) for node in nodes if node.id is not None]
        aliases = []
        if node_ids:
            for node_id in node_ids:
                aliases.extend(kg_repo.list_aliases_by_node(session, node_id))
        edges = kg_repo.list_all_edges_by_subject(session, subject, status=None)

    embedding_texts = [f"{node.canonical_name}\n{node.summary}".strip() for node in nodes]
    embeddings = await aembed_texts(embedding_texts) if embedding_texts else []
    index = ResolutionIndex(subject=subject)
    record_by_node_id: dict[int, ExistingNodeRecord] = {}

    for node, embedding in zip(nodes, embeddings):
        if node.id is None:
            continue
        record = ExistingNodeRecord(node=node, summary=node.summary or "", embedding=embedding)
        record_by_node_id[int(node.id)] = record
        index.normalized_map[(node.node_type, node.normalized_name)] = record
        index.records_by_type.setdefault(node.node_type, []).append(record)

    for alias in aliases:
        record = record_by_node_id.get(int(alias.node_id))
        if record is None or alias.status not in {"active", "pending"}:
            continue
        index.alias_map[(record.node.node_type, alias.normalized_alias)] = record

    for edge in edges:
        parent_id: int | None = None
        child_id: int | None = None
        child_type: str | None = None
        if edge.edge_type == "defined_by":
            parent_id = edge.source_node_id
            child_id = edge.target_node_id
            child_type = "Definition"
        elif edge.edge_type == "illustrated_by":
            parent_id = edge.source_node_id
            child_id = edge.target_node_id
            child_type = "Example"
        elif edge.edge_type == "belongs_to_topic":
            parent_id = edge.target_node_id
            child_id = edge.source_node_id
            child_type = "Example"

        if parent_id is None or child_id is None or child_type is None:
            continue
        child_record = record_by_node_id.get(child_id)
        if child_record is None or child_record.node.node_type != child_type:
            continue
        children_by_type = index.children_by_parent.setdefault(parent_id, {})
        children_by_type.setdefault(child_type, []).append(child_record)

    return index


def _match_primary_candidate(
    representative_name: str,
    representative_type: str,
    candidate_summary: str,
    candidate_embedding: list[float],
    index: ResolutionIndex,
) -> ResolveResult:
    normalized_name = normalize_name(representative_name)
    exact_match = index.normalized_map.get((representative_type, normalized_name))
    if exact_match is not None:
        return ResolveResult(
            decision="exact",
            matched_node_id=int(exact_match.node.id or 0),
            is_content_update=_has_content_update(candidate_summary, exact_match.summary),
        )

    alias_match = index.alias_map.get((representative_type, normalized_name))
    if alias_match is not None:
        return ResolveResult(
            decision="alias",
            matched_node_id=int(alias_match.node.id or 0),
            is_content_update=_has_content_update(candidate_summary, alias_match.summary),
            new_aliases=[representative_name],
        )

    if not candidate_embedding:
        return ResolveResult(decision="no_match")

    same_type_records = index.records_by_type.get(representative_type, [])
    best_record: ExistingNodeRecord | None = None
    best_similarity = 0.0
    for record in same_type_records:
        similarity = _cosine_similarity(candidate_embedding, record.embedding)
        if similarity > best_similarity:
            best_similarity = similarity
            best_record = record

    if best_record is None or best_similarity < _PRIMARY_SIMILARITY_THRESHOLD:
        return ResolveResult(decision="no_match")

    return ResolveResult(
        decision="exact",
        matched_node_id=int(best_record.node.id or 0),
        is_content_update=_has_content_update(candidate_summary, best_record.summary),
    )


def _resolve_parent_node_id(
    parent_name: str,
    candidate_name_to_resolved_node_id: dict[str, int],
    index: ResolutionIndex,
) -> int | None:
    mapped_parent_id = candidate_name_to_resolved_node_id.get(parent_name)
    if mapped_parent_id is not None:
        return mapped_parent_id

    normalized_parent = normalize_name(parent_name)
    for parent_type in ("Topic", "Concept", "Method"):
        record = index.normalized_map.get((parent_type, normalized_parent))
        if record is not None:
            return int(record.node.id or 0)
        alias_record = index.alias_map.get((parent_type, normalized_parent))
        if alias_record is not None:
            return int(alias_record.node.id or 0)
    return None


def _match_secondary_candidate(
    *,
    representative_name: str,
    representative_type: str,
    parent_name: str | None,
    candidate_summary: str,
    candidate_embedding: list[float],
    index: ResolutionIndex,
    candidate_name_to_resolved_node_id: dict[str, int],
) -> ResolveResult:
    normalized_name = normalize_name(representative_name)
    exact_match = index.normalized_map.get((representative_type, normalized_name))
    if exact_match is not None:
        return ResolveResult(
            decision="exact",
            matched_node_id=int(exact_match.node.id or 0),
            is_content_update=_has_content_update(candidate_summary, exact_match.summary),
        )

    alias_match = index.alias_map.get((representative_type, normalized_name))
    if alias_match is not None:
        return ResolveResult(
            decision="alias",
            matched_node_id=int(alias_match.node.id or 0),
            is_content_update=_has_content_update(candidate_summary, alias_match.summary),
            new_aliases=[representative_name],
        )

    if not parent_name or not candidate_embedding:
        return ResolveResult(decision="no_match")

    parent_node_id = _resolve_parent_node_id(parent_name, candidate_name_to_resolved_node_id, index)
    if parent_node_id is None:
        return ResolveResult(decision="no_match")

    sibling_records = index.children_by_parent.get(parent_node_id, {}).get(representative_type, [])
    best_record: ExistingNodeRecord | None = None
    best_similarity = 0.0
    for record in sibling_records:
        similarity = _cosine_similarity(candidate_embedding, record.embedding)
        if similarity > best_similarity:
            best_similarity = similarity
            best_record = record

    if best_record is None or best_similarity < _SECONDARY_SIMILARITY_THRESHOLD:
        return ResolveResult(decision="no_match")

    return ResolveResult(
        decision="exact",
        matched_node_id=int(best_record.node.id or 0),
        is_content_update=_has_content_update(candidate_summary, best_record.summary),
    )


def _resolve_edge_endpoint(
    *,
    session,
    subject: str,
    name: str,
    candidate_name_to_resolved_node_id: dict[str, int],
) -> int | None:
    mapped = candidate_name_to_resolved_node_id.get(name)
    if mapped is not None:
        return mapped

    normalized_name = normalize_name(name)
    for node_type in ("Topic", "Concept", "Definition", "Method", "Example"):
        node = kg_repo.find_node_by_normalized_name(
            session,
            subject,
            normalized_name,
            node_type,
        )
        if node is not None and node.id is not None:
            return int(node.id)
    return None


async def resolve_nodes_node(state: KGDigestState) -> KGDigestState:
    """Resolve clustered candidates against existing graph nodes."""

    with managed_session() as session:
        digest_logger = workflow_logger(state)
        try:
            clustered_candidates = list(state.get("clustered_candidates", []))
            subject = state["subject"]
            job_id = state["job_id"]
            resolution_index = await _build_resolution_index(subject)
            digest_logger.info(
                "kg_resolution_index_built",
                cluster_count=len(clustered_candidates),
                indexed_type_count=len(resolution_index.records_by_type),
                indexed_node_count=sum(
                    len(records) for records in resolution_index.records_by_type.values()
                ),
            )

            candidate_name_to_resolved_node_id: dict[str, int] = {}
            cluster_id_to_resolved_node_id: dict[int, int] = {}
            new_node_ids: list[int] = []
            updated_node_ids: list[int] = []
            merged_node_ids: list[int] = []
            candidate_embeddings = (
                await aembed_texts(
                    [
                        f"{candidate.representative.name}\n{candidate.merged_summary}".strip()
                        for candidate in clustered_candidates
                    ]
                )
                if clustered_candidates
                else []
            )

            for cluster_index, clustered_candidate in enumerate(clustered_candidates):
                representative = clustered_candidate.representative
                candidate_embedding = (
                    candidate_embeddings[cluster_index]
                    if cluster_index < len(candidate_embeddings)
                    else []
                )
                if representative.node_type in _PRIMARY_NODE_TYPES:
                    result = _match_primary_candidate(
                        representative.name,
                        representative.node_type,
                        clustered_candidate.merged_summary,
                        candidate_embedding,
                        resolution_index,
                    )
                elif representative.node_type in _SECONDARY_NODE_TYPES:
                    result = _match_secondary_candidate(
                        representative_name=representative.name,
                        representative_type=representative.node_type,
                        parent_name=representative.parent_entity_name or representative.taxonomy_hint,
                        candidate_summary=clustered_candidate.merged_summary,
                        candidate_embedding=candidate_embedding,
                        index=resolution_index,
                        candidate_name_to_resolved_node_id=candidate_name_to_resolved_node_id,
                    )
                else:
                    result = ResolveResult(decision="no_match")

                if result.decision in {"exact", "alias"} and result.matched_node_id is not None:
                    node_id = result.matched_node_id
                    cluster_id_to_resolved_node_id[cluster_index] = node_id
                    for member in clustered_candidate.members:
                        candidate_name_to_resolved_node_id[member.name] = node_id
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
                        if node_id not in updated_node_ids:
                            updated_node_ids.append(node_id)
                else:
                    node = create_new_node(
                        session,
                        subject=subject,
                        clustered_candidate=clustered_candidate,
                        job_id=job_id,
                    )
                    node_id = int(node.id or 0)
                    cluster_id_to_resolved_node_id[cluster_index] = node_id
                    for member in clustered_candidate.members:
                        candidate_name_to_resolved_node_id[member.name] = node_id
                    for chunk_id in clustered_candidate.source_chunk_ids:
                        create_node_evidence(
                            session,
                            subject=subject,
                            node_id=node_id,
                            chunk_id=chunk_id,
                            job_id=job_id,
                        )
                    new_node_ids.append(node_id)

                digest_logger.info(
                    "resolve_node_complete",
                    name=representative.name,
                    node_type=representative.node_type,
                    decision=result.decision,
                    matched_node_id=result.matched_node_id,
                )
                if clustered_candidates and (cluster_index + 1) % 20 == 0:
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


def compute_edge_confidence(active_evidence_count: int, *, max_confidence: float = 0.95) -> float:
    if active_evidence_count <= 0:
        return 0.0
    base = 1.0 - 1.0 / (1.0 + active_evidence_count)
    return max(0.0, min(max_confidence, base))


async def resolve_edges_node(state: KGDigestState) -> KGDigestState:
    """Resolve candidate edges against the current graph."""

    with managed_session() as session:
        digest_logger = workflow_logger(state)
        try:
            all_candidate_edges = state.get("all_candidate_edges", [])
            subject = state["subject"]
            job_id = state["job_id"]
            candidate_name_to_resolved_node_id = state.get("candidate_name_to_resolved_node_id", {})
            subject_row = session.exec(select(Subject).where(Subject.slug == subject)).first()
            if subject_row is None or subject_row.id is None:
                return {**state, "error": f"resolve_edges_failed: unknown subject `{subject}`"}

            new_edge_ids: list[int] = []
            updated_edge_ids: list[int] = []

            for edge_candidate, chunk_id in all_candidate_edges:
                source_id = _resolve_edge_endpoint(
                    session=session,
                    subject=subject,
                    name=edge_candidate.source_name,
                    candidate_name_to_resolved_node_id=candidate_name_to_resolved_node_id,
                )
                target_id = _resolve_edge_endpoint(
                    session=session,
                    subject=subject,
                    name=edge_candidate.target_name,
                    candidate_name_to_resolved_node_id=candidate_name_to_resolved_node_id,
                )
                if source_id is None or target_id is None or source_id == target_id:
                    continue

                matched_edge = kg_repo.find_edge(session, source_id, target_id, edge_candidate.edge_type)
                if matched_edge is None:
                    edge = kg_repo.create_knowledge_edge(
                        session,
                        KnowledgeEdge(
                            user_id=subject_row.user_id,
                            subject_id=int(subject_row.id),
                            source_node_id=source_id,
                            target_node_id=target_id,
                            edge_type=edge_candidate.edge_type,
                            description=edge_candidate.description,
                            weight=1.0,
                            confidence=compute_edge_confidence(1),
                            status="pending",
                        ),
                    )
                    edge_id = int(edge.id or 0)
                    create_edge_evidence(
                        session,
                        subject=subject,
                        edge_id=edge_id,
                        chunk_id=chunk_id,
                        job_id=job_id,
                    )
                    new_edge_ids.append(edge_id)
                    continue

                edge_id = int(matched_edge.id or 0)
                create_edge_evidence(
                    session,
                    subject=subject,
                    edge_id=edge_id,
                    chunk_id=chunk_id,
                    job_id=job_id,
                )
                active_evidence_count = kg_repo.count_active_evidence(session, "edge", edge_id)
                matched_edge.description = matched_edge.description or edge_candidate.description
                matched_edge.confidence = compute_edge_confidence(active_evidence_count + 1)
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
