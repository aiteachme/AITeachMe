"""Knowledge graph resolve-nodes node."""


from __future__ import annotations

import json
from dataclasses import dataclass, field
from time import perf_counter

from sqlmodel import select

from app.shared.infra.database import managed_session
from app.shared.infra.embedding import aembed_texts
from app.models.knowledge_relation import EdgeRevision, KnowledgeEdge
from app.models.knowledge_unit import KnowledgeUnit
from app.repositories import knowledge_build_repo
from app.utils.job_helpers import update_job_progress
from app.utils.knowledge_helpers import normalize_name
from app.utils.time import utcnow
from app.workflows.digest.knowledge_graph.mutations import (
    create_alias_if_new,
    create_edge_evidence,
    create_new_knowledge_unit,
    create_node_evidence,
    create_updated_revision,
)
from app.workflows.digest.knowledge_graph.lib.candidate_identity import (
    build_candidate_name_key,
    candidate_lookup_keys,
    normalize_scope_name,
)
from app.workflows.digest.knowledge_graph.lib.embedding_cache import (
    compute_embedding_text_hash,
    load_subject_embedding_cache,
    write_subject_embedding_cache,
)
from app.workflows.digest.knowledge_graph.lib.impact_analyzer import analyze_impact
from app.workflows.digest.knowledge_graph.lib.resolver import (
    ResolveResult,
    compute_edge_confidence,
    resolve_edge,
)
from app.models.knowledge_taxonomy import (
    PARENT_KNOWLEDGE_UNIT_TYPES,
    PRIMARY_KNOWLEDGE_UNIT_TYPES,
    SECONDARY_KNOWLEDGE_UNIT_TYPES,
    normalize_knowledge_unit_type,
)
from app.workflows.digest.knowledge_graph.state import KnowledgeDigestState
from app.workflows.digest.knowledge_graph.support import workflow_logger

_PRIMARY_NODE_TYPES = PRIMARY_KNOWLEDGE_UNIT_TYPES
_SECONDARY_NODE_TYPES = SECONDARY_KNOWLEDGE_UNIT_TYPES
_PRIMARY_SIMILARITY_THRESHOLD = 0.80
_SECONDARY_SIMILARITY_THRESHOLD = 0.85

class ExistingNodeRecord:
    node: KnowledgeUnit
    summary: str
    embedding: list[float]


@dataclass(slots=True)
class ResolutionIndex:
    subject: str
    normalized_map: dict[tuple[str, str], ExistingNodeRecord] = field(default_factory=dict)
    alias_map: dict[tuple[str, str], ExistingNodeRecord] = field(default_factory=dict)
    records_by_type: dict[str, list[ExistingNodeRecord]] = field(default_factory=dict)
    children_by_parent: dict[int, dict[str, list[ExistingNodeRecord]]] = field(default_factory=dict)


def _load_alias_entries(raw: str) -> list[dict[str, object]]:
    try:
        payload = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


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
        nodes = list(
            session.exec(
                select(KnowledgeUnit).where(
                    KnowledgeUnit.subject == subject,
                    KnowledgeUnit.status.in_(["active", "pending"]),
                )
            ).all()
        )
        edges = list(
            session.exec(
                select(KnowledgeEdge).where(
                    KnowledgeEdge.subject == subject,
                    KnowledgeEdge.status.in_(["active", "pending"]),
                )
            ).all()
        )

    if not nodes:
        return ResolutionIndex(subject=subject)

    cache_payload = load_subject_embedding_cache(subject)
    embedding_by_node_id: dict[int, list[float]] = {}
    missing_node_ids: list[int] = []
    missing_texts: list[str] = []
    stale_node_ids = {str(node_id) for node_id in cache_payload}

    for node in nodes:
        if node.id is None:
            continue
        stale_node_ids.discard(str(node.id))
        embedding_text = f"{node.canonical_name}\n{node.summary}".strip()
        text_hash = compute_embedding_text_hash(embedding_text)
        cached = cache_payload.get(str(node.id), {})
        cached_embedding = cached.get("embedding")
        if cached.get("text_hash") == text_hash and isinstance(cached_embedding, list):
            embedding_by_node_id[node.id] = [
                float(item)
                for item in cached_embedding
                if isinstance(item, (float, int))
            ]
            continue

        missing_node_ids.append(node.id)
        missing_texts.append(embedding_text)
        cache_payload[str(node.id)] = {
            "text_hash": text_hash,
            "canonical_name": node.canonical_name,
            "updated_at": node.updated_at.isoformat(),
        }

    if missing_texts:
        missing_embeddings = await aembed_texts(missing_texts)
        for node_id, embedding in zip(missing_node_ids, missing_embeddings, strict=False):
            embedding_by_node_id[node_id] = embedding
            cache_payload[str(node_id)]["embedding"] = embedding

    for stale_node_id in stale_node_ids:
        cache_payload.pop(stale_node_id, None)
    write_subject_embedding_cache(subject, cache_payload)

    index = ResolutionIndex(subject=subject)
    record_by_node_id: dict[int, ExistingNodeRecord] = {}

    for node in nodes:
        if node.id is None:
            continue
        embedding = embedding_by_node_id.get(node.id, [])
        record = ExistingNodeRecord(node=node, summary=node.summary, embedding=embedding)
        record_by_node_id[node.id] = record
        node_type = normalize_knowledge_unit_type(node.node_type)
        index.normalized_map[(node_type, node.normalized_name)] = record
        index.records_by_type.setdefault(node_type, []).append(record)

        for alias_entry in _load_alias_entries(node.aliases_json):
            if str(alias_entry.get("status", "active")) != "active":
                continue
            normalized_alias = str(alias_entry.get("normalized_alias", "")).strip()
            if not normalized_alias:
                continue
            index.alias_map[(node_type, normalized_alias)] = record

    for edge in edges:
        parent_id: int | None = None
        child_id: int | None = None
        child_type: str | None = None
        if edge.edge_type == "derivation":
            parent_id = edge.target_node_id
            child_id = edge.source_node_id
            child_type = "definition"
        elif edge.edge_type == "example_of":
            parent_id = edge.target_node_id
            child_id = edge.source_node_id
            child_type = "example"
        elif edge.edge_type == "application":
            parent_id = edge.target_node_id
            child_id = edge.source_node_id
            child_type = "exercise"

        if parent_id is None or child_id is None or child_type is None:
            continue

        child_record = record_by_node_id.get(child_id)
        if child_record is None or normalize_knowledge_unit_type(child_record.node.node_type) != child_type:
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
            matched_node_id=exact_match.node.id,
            is_content_update=_has_content_update(candidate_summary, exact_match.summary),
        )

    alias_match = index.alias_map.get((representative_type, normalized_name))
    if alias_match is not None:
        return ResolveResult(
            decision="alias",
            matched_node_id=alias_match.node.id,
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
        matched_node_id=best_record.node.id,
        is_content_update=_has_content_update(candidate_summary, best_record.summary),
    )


def _resolve_parent_node_id(
    parent_name: str,
    taxonomy_hint: str | None,
    candidate_lookup_to_resolved_node_id: dict[str, int],
    index: ResolutionIndex,
) -> int | None:
    scope = normalize_scope_name(taxonomy_hint)
    for parent_type in PARENT_KNOWLEDGE_UNIT_TYPES:
        for lookup_key in (
            build_candidate_name_key(parent_type, parent_name, scope=scope),
            build_candidate_name_key(parent_type, parent_name, scope=None),
        ):
            mapped_parent_id = candidate_lookup_to_resolved_node_id.get(lookup_key)
            if mapped_parent_id is not None:
                return mapped_parent_id

    normalized_parent = normalize_name(parent_name)
    for parent_type in PARENT_KNOWLEDGE_UNIT_TYPES:
        record = index.normalized_map.get((parent_type, normalized_parent))
        if record is not None:
            return record.node.id
        alias_record = index.alias_map.get((parent_type, normalized_parent))
        if alias_record is not None:
            return alias_record.node.id
    return None


def _match_secondary_candidate(
    *,
    representative_name: str,
    representative_type: str,
    parent_name: str | None,
    taxonomy_hint: str | None,
    candidate_summary: str,
    candidate_embedding: list[float],
    index: ResolutionIndex,
    candidate_lookup_to_resolved_node_id: dict[str, int],
) -> ResolveResult:
    if not parent_name or not candidate_embedding:
        return ResolveResult(decision="no_match")

    parent_node_id = _resolve_parent_node_id(
        parent_name,
        taxonomy_hint,
        candidate_lookup_to_resolved_node_id,
        index,
    )
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
        matched_node_id=best_record.node.id,
        is_content_update=_has_content_update(candidate_summary, best_record.summary),
    )


async def resolve_nodes_node(state: KnowledgeDigestState) -> KnowledgeDigestState:
    """Resolve clustered candidates against existing graph nodes."""

    with managed_session() as session:
        digest_logger = workflow_logger(state)
        try:
            clustered_candidates = list(state.get("clustered_candidates", []))
            subject = state["subject"]
            job_id = state["job_id"]
            resolution_index_started_at = perf_counter()
            resolution_index = await _build_resolution_index(subject)
            resolution_index_ms = int((perf_counter() - resolution_index_started_at) * 1000)
            digest_logger.info(
                "knowledge_resolution_index_built",
                cluster_count=len(clustered_candidates),
                indexed_type_count=len(resolution_index.records_by_type),
                indexed_node_count=sum(
                    len(records) for records in resolution_index.records_by_type.values()
                ),
                resolution_index_ms=resolution_index_ms,
            )

            candidate_lookup_to_resolved_node_id: dict[str, int] = {}
            cluster_id_to_resolved_node_id: dict[int, int] = {}
            new_node_ids: list[int] = []
            updated_node_ids: list[int] = []
            merged_node_ids: list[int] = []
            pending_write_count = 0
            persist_started_at = perf_counter()
            no_match_count = 0
            secondary_no_match_count = 0

            def _commit_pending_writes() -> None:
                nonlocal pending_write_count
                if pending_write_count <= 0:
                    return
                session.commit()
                pending_write_count = 0
            candidate_embedding_started_at = perf_counter()
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
            candidate_embedding_ms = int((perf_counter() - candidate_embedding_started_at) * 1000)

            for cluster_index, clustered_candidate in enumerate(clustered_candidates):
                representative = clustered_candidate.representative
                representative.node_type = normalize_knowledge_unit_type(representative.node_type)
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
                        taxonomy_hint=representative.taxonomy_hint,
                        candidate_summary=clustered_candidate.merged_summary,
                        candidate_embedding=candidate_embedding,
                        index=resolution_index,
                        candidate_lookup_to_resolved_node_id=candidate_lookup_to_resolved_node_id,
                    )
                else:
                    result = ResolveResult(decision="no_match")

                if result.decision in {"exact", "alias"} and result.matched_node_id is not None:
                    node_id = result.matched_node_id
                    cluster_id_to_resolved_node_id[cluster_index] = node_id
                    for member in clustered_candidate.members:
                        for lookup_key in candidate_lookup_keys(member):
                            candidate_lookup_to_resolved_node_id[lookup_key] = node_id
                    for chunk_id in clustered_candidate.source_chunk_ids:
                        create_node_evidence(
                            session,
                            subject=subject,
                            node_id=node_id,
                            chunk_id=chunk_id,
                            job_id=job_id,
                            clustered_candidate=clustered_candidate,
                            auto_commit=False,
                        )
                        pending_write_count += 1
                    for alias_name in result.new_aliases:
                        create_alias_if_new(
                            session,
                            node_id=node_id,
                            alias_name=alias_name,
                            job_id=job_id,
                            auto_commit=False,
                        )
                        pending_write_count += 1
                    if result.is_content_update:
                        create_updated_revision(
                            session,
                            node_id=node_id,
                            clustered_candidate=clustered_candidate,
                            job_id=job_id,
                            auto_commit=False,
                        )
                        pending_write_count += 1
                        updated_node_ids.append(node_id)
                else:
                    node = create_new_knowledge_unit(
                        session,
                        subject=subject,
                        clustered_candidate=clustered_candidate,
                        job_id=job_id,
                        auto_commit=False,
                    )
                    pending_write_count += 3
                    node_id = node.id
                    if node_id is None:
                        continue
                    cluster_id_to_resolved_node_id[cluster_index] = node_id
                    for member in clustered_candidate.members:
                        for lookup_key in candidate_lookup_keys(member):
                            candidate_lookup_to_resolved_node_id[lookup_key] = node_id
                    for chunk_id in clustered_candidate.source_chunk_ids:
                        create_node_evidence(
                            session,
                            subject=subject,
                            node_id=node_id,
                            chunk_id=chunk_id,
                            job_id=job_id,
                            clustered_candidate=clustered_candidate,
                            auto_commit=False,
                        )
                        pending_write_count += 1
                    new_node_ids.append(node_id)

                if result.decision == "no_match":
                    no_match_count += 1
                    if representative.node_type in _SECONDARY_NODE_TYPES:
                        secondary_no_match_count += 1
                if result.decision != "no_match" or representative.node_type not in _SECONDARY_NODE_TYPES:
                    digest_logger.info(
                        "resolve_node_complete",
                        name=representative.name,
                        node_type=representative.node_type,
                        decision=result.decision,
                        matched_node_id=result.matched_node_id,
                    )
                if clustered_candidates and (cluster_index + 1) % 20 == 0:
                    _commit_pending_writes()
                    progress = 50 + int(15 * (cluster_index + 1) / len(clustered_candidates))
                    update_job_progress(
                        session,
                        job_id=job_id,
                        job_type="graph",
                        progress=min(progress, 65),
                        current_step="resolve_nodes",
                    )

            _commit_pending_writes()
            node_persist_ms = int((perf_counter() - persist_started_at) * 1000)
            update_job_progress(
                session,
                job_id=job_id,
                job_type="graph",
                progress=65,
                current_step="resolve_nodes",
            )
            knowledge_build_repo.update_digest_job(
                session,
                job_id,
                nodes_added=len(new_node_ids),
                nodes_updated=len(updated_node_ids),
                nodes_merged=len(merged_node_ids),
            )
            digest_logger.info(
                "knowledge_workflow_resolve_nodes_complete",
                new_nodes=len(new_node_ids),
                updated_nodes=len(updated_node_ids),
                total_resolved=len(candidate_lookup_to_resolved_node_id),
            )
            return {
                **state,
                "candidate_lookup_to_resolved_node_id": candidate_lookup_to_resolved_node_id,
                "cluster_id_to_resolved_node_id": cluster_id_to_resolved_node_id,
                "new_node_ids": new_node_ids,
                "updated_node_ids": updated_node_ids,
                "merged_node_ids": merged_node_ids,
                "resolution_index_ms": resolution_index_ms,
                "candidate_embedding_ms": candidate_embedding_ms,
                "node_persist_ms": node_persist_ms,
                "no_match_count": no_match_count,
                "secondary_no_match_count": secondary_no_match_count,
            }
        except Exception as exc:
            digest_logger.error("knowledge_workflow_resolve_nodes_failed", error=str(exc), exc_info=True)
            return {**state, "error": f"resolve_nodes_failed: {exc}"}

__all__ = ["resolve_nodes_node"]

