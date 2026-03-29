"""Preparation and extraction nodes for the graph lane."""

from __future__ import annotations

import asyncio

from sqlmodel import select

from app.core.config import get_settings
from app.core.database import managed_session
from app.models import RetrievalChunk
from app.repositories.knowledge import kg_repo
from app.utils.job_helpers import update_job_progress
from app.workflows.digest.kg.services.clusterer import cluster_candidates
from app.workflows.digest.kg.services.extractor import (
    CandidateEdge,
    ChunkExtractionResult,
    extract_candidates,
)
from app.workflows.digest.kg.state import KGDigestState
from app.workflows.digest.kg.support import workflow_logger
from app.workflows.digest.unified.models import ChapterPriors, TopicAnchor, TopicAnchorSnapshot
from app.workflows.digest.unified.session import get_unified_build_session

def _resolve_extract_parallelism() -> int:
    settings = get_settings()
    # Use dedicated config, bounded between 1 and llm_concurrency_limit
    return max(1, min(settings.kg_extract_max_parallelism, settings.llm_concurrency_limit))


def _build_taxonomy_hints(chapter_priors: ChapterPriors | None) -> set[str]:
    if chapter_priors is None:
        return set()

    hints: set[str] = set()
    for chapter in chapter_priors.chapters:
        hints.add(chapter.title)
        hints.update(chapter.section_titles)
        hints.update(chapter.key_terms)
    return {hint for hint in hints if hint}


def _apply_taxonomy_hints(result: ChunkExtractionResult, taxonomy_hints: set[str]) -> None:
    if not taxonomy_hints:
        return

    for node in result.nodes:
        node_name_lower = node.name.lower()
        for hint in taxonomy_hints:
            hint_lower = hint.lower()
            if hint_lower in node_name_lower or node_name_lower in hint_lower:
                node.taxonomy_hint = hint
                break


def _build_early_topic_snapshot(state: KGDigestState, clustered_candidates) -> TopicAnchorSnapshot:
    chunk_id_to_chunk_uid = state.get("chunk_id_to_chunk_uid", {})
    anchors: list[TopicAnchor] = []
    for cluster in clustered_candidates[:80]:
        representative = cluster.representative
        if not representative.name:
            continue
        chunk_uids = [
            chunk_id_to_chunk_uid[chunk_id]
            for chunk_id in cluster.source_chunk_ids
            if chunk_id in chunk_id_to_chunk_uid
        ]
        if not chunk_uids:
            continue
        anchors.append(
            TopicAnchor(
                topic_name=representative.name,
                node_type=representative.node_type,
                confidence=min(0.9, 0.5 + 0.06 * len(cluster.members)),
                chunk_uids=list(dict.fromkeys(chunk_uids)),
            )
        )
    return TopicAnchorSnapshot(anchors=anchors)


async def acquire_lock_node(state: KGDigestState) -> KGDigestState:
    """Acquire a subject-scoped graph build lock."""

    with managed_session() as session:
        digest_logger = workflow_logger(state)
        digest_logger.info("kg_workflow_acquire_lock_started")
        acquired = kg_repo.acquire_subject_build_lock(
            session,
            state["subject"],
            state["job_id"],
        )
        if not acquired:
            digest_logger.warning("kg_workflow_lock_conflict")
            return {**state, "lock_acquired": False, "error": "lock_conflict"}

        update_job_progress(
            session,
            job_id=state["job_id"],
            job_type="graph",
            progress=5,
            current_step="acquire_lock",
        )
        kg_repo.update_digest_job(session, state["job_id"], status="processing")
        digest_logger.info("kg_workflow_acquire_lock_completed")
        return {**state, "lock_acquired": True}


async def prepare_node(state: KGDigestState) -> KGDigestState:
    """Load canonical chunk ids from the unified build session."""

    with managed_session() as session:
        digest_logger = workflow_logger(state)
        try:
            build_session_id = state.get("build_session_id", "")
            if not build_session_id:
                return {**state, "error": "missing_build_session_id"}

            unified_session = get_unified_build_session(build_session_id)
            materialized = unified_session.materialized
            chunk_ids = list(materialized.chunk_ids)
            if not chunk_ids:
                return {**state, "error": "no_ready_digest_inputs"}

            update_job_progress(
                session,
                job_id=state["job_id"],
                job_type="graph",
                progress=10,
                current_step="prepare",
            )
            digest_logger.info(
                "kg_workflow_prepare_complete",
                build_session_id=build_session_id,
                document_count=len(materialized.document_ids),
                chunk_count=len(chunk_ids),
                source_file_ids=materialized.source_file_ids,
            )
            return {
                **state,
                "shared_inputs": unified_session.shared_inputs,
                "chunk_ids": chunk_ids,
                "chunk_uid_to_chunk_id": dict(materialized.chunk_uid_to_chunk_id),
                "chunk_id_to_chunk_uid": dict(materialized.chunk_id_to_chunk_uid),
            }
        except Exception as exc:
            digest_logger.error("kg_workflow_prepare_failed", error=str(exc), exc_info=True)
            return {**state, "error": f"prepare_failed: {exc}"}


async def extract_node(state: KGDigestState) -> KGDigestState:
    """Extract candidate nodes and edges chunk by chunk with controlled parallelism."""

    with managed_session() as session:
        digest_logger = workflow_logger(state)
        try:
            chunk_ids = list(state.get("chunk_ids", []))
            extract_parallelism = min(_resolve_extract_parallelism(), max(1, len(chunk_ids)))
            build_session_id = state.get("build_session_id", "")
            chapter_priors: ChapterPriors | None = None
            subject_context = ""
            if build_session_id:
                unified_session = get_unified_build_session(build_session_id)
                settings = get_settings()
                chapter_priors = await unified_session.wait_for_chapter_priors(
                    timeout_ms=settings.digest_chapter_priors_timeout_ms
                )
                if unified_session.shared_inputs and unified_session.shared_inputs.subject_profile:
                    subject_context = unified_session.shared_inputs.subject_profile.build_context_string()

            taxonomy_hints = _build_taxonomy_hints(chapter_priors)
            digest_logger.info(
                "kg_extract_started",
                chunk_count=len(chunk_ids),
                parallelism=extract_parallelism,
                has_chapter_priors=chapter_priors is not None,
                taxonomy_hint_count=len(taxonomy_hints),
            )
            update_job_progress(
                session,
                job_id=state["job_id"],
                job_type="graph",
                progress=15,
                current_step="extract",
            )

            if not chunk_ids:
                update_job_progress(
                    session,
                    job_id=state["job_id"],
                    job_type="graph",
                    progress=40,
                    current_step="extract",
                )
                return {
                    **state,
                    "candidates": [],
                    "all_candidate_edges": [],
                }

            chunk_rows = list(
                session.exec(
                    select(RetrievalChunk).where(
                        RetrievalChunk.id.in_(chunk_ids),  # type: ignore[union-attr]
                    )
                ).all()
            )
            chunk_map = {chunk.id: chunk for chunk in chunk_rows if chunk.id is not None}
            ordered_results = [ChunkExtractionResult() for _ in chunk_ids]
            all_candidate_edges: list[tuple[CandidateEdge, int]] = []
            success_chunk_count = 0
            failed_chunk_count = 0
            failure_samples: list[dict[str, str | int]] = []
            semaphore = asyncio.Semaphore(extract_parallelism)

            async def _extract_single(index: int, chunk_id: int):
                chunk = chunk_map.get(chunk_id)
                if chunk is None:
                    return index, chunk_id, ChunkExtractionResult(), [], "missing"

                try:
                    async with semaphore:
                        result = await extract_candidates(
                            chunk_content=chunk.content,
                            chunk_title=chunk.title,
                            header_path=chunk.header_path,
                            doc_source_type=getattr(chunk, "source_type", None),
                            subject_context=subject_context,
                        )
                    _apply_taxonomy_hints(result, taxonomy_hints)
                    edge_payload = [(edge, chunk_id) for edge in result.edges]
                    return index, chunk_id, result, edge_payload, None
                except Exception as exc:
                    digest_logger.warning("kg_chunk_extraction_failed", chunk_id=chunk_id, error=str(exc))
                    return index, chunk_id, ChunkExtractionResult(), [], str(exc)

            tasks = [
                asyncio.create_task(_extract_single(index, chunk_id))
                for index, chunk_id in enumerate(chunk_ids)
            ]
            completed_count = 0
            for task in asyncio.as_completed(tasks):
                index, chunk_id, result, edge_payload, error = await task
                ordered_results[index] = result

                if error == "missing":
                    failed_chunk_count += 1
                    if len(failure_samples) < 5:
                        failure_samples.append({"chunk_id": chunk_id, "error": "missing"})
                    digest_logger.warning("kg_extract_chunk_missing", chunk_id=chunk_id)
                elif error is not None:
                    failed_chunk_count += 1
                    if len(failure_samples) < 5:
                        failure_samples.append({"chunk_id": chunk_id, "error": error[:180]})
                    digest_logger.warning(
                        "kg_extract_chunk_failed",
                        chunk_id=chunk_id,
                        error=error,
                    )
                else:
                    success_chunk_count += 1
                    all_candidate_edges.extend(edge_payload)

                completed_count += 1
                if completed_count % 5 == 0 or completed_count == len(tasks):
                    progress = 10 + int(30 * completed_count / len(tasks))
                    update_job_progress(
                        session,
                        job_id=state["job_id"],
                        job_type="graph",
                        progress=min(progress, 40),
                        current_step="extract",
                    )

            update_job_progress(
                session,
                job_id=state["job_id"],
                job_type="graph",
                progress=40,
                current_step="extract",
            )
            total_nodes = sum(len(result.nodes) for result in ordered_results)
            total_edges = len(all_candidate_edges)
            digest_logger.info(
                "kg_workflow_extract_complete",
                total_chunks=len(chunk_ids),
                success_chunk_count=success_chunk_count,
                failed_chunk_count=failed_chunk_count,
                results_count=len(ordered_results),
                total_nodes=total_nodes,
                total_edges=total_edges,
                parallelism=extract_parallelism,
                failure_samples=failure_samples,
            )
            if chunk_ids and success_chunk_count == 0:
                error_message = "extract_failed: all_chunk_extractions_failed"
                digest_logger.error(
                    "kg_workflow_extract_zero_success",
                    total_chunks=len(chunk_ids),
                    failed_chunk_count=failed_chunk_count,
                    failure_samples=failure_samples,
                )
                return {
                    **state,
                    "candidates": ordered_results,
                    "all_candidate_edges": all_candidate_edges,
                    "error": error_message,
                }
            if chunk_ids and total_nodes == 0:
                error_message = "extract_failed: zero_candidate_nodes"
                digest_logger.error(
                    "kg_workflow_extract_zero_nodes",
                    total_chunks=len(chunk_ids),
                    success_chunk_count=success_chunk_count,
                    failed_chunk_count=failed_chunk_count,
                    failure_samples=failure_samples,
                )
                return {
                    **state,
                    "candidates": ordered_results,
                    "all_candidate_edges": all_candidate_edges,
                    "error": error_message,
                }
            return {
                **state,
                "candidates": ordered_results,
                "all_candidate_edges": all_candidate_edges,
            }
        except Exception as exc:
            digest_logger.error("kg_workflow_extract_failed", error=str(exc), exc_info=True)
            return {**state, "error": f"extract_failed: {exc}"}


async def cluster_node(state: KGDigestState) -> KGDigestState:
    """Cluster candidate nodes within the current batch."""

    with managed_session() as session:
        digest_logger = workflow_logger(state)
        try:
            results = state.get("candidates", [])
            chunk_ids = state.get("chunk_ids", [])
            digest_logger.info(
                "kg_cluster_started",
                result_count=len(results),
                chunk_count=len(chunk_ids),
            )

            all_pairs = [
                (node, chunk_id)
                for chunk_id, result in zip(chunk_ids, results)
                for node in result.nodes
            ]
            if not all_pairs:
                update_job_progress(
                    session,
                    job_id=state["job_id"],
                    job_type="graph",
                    progress=50,
                    current_step="cluster",
                )
                return {
                    **state,
                    "clustered_candidates": [],
                    "candidate_name_to_cluster_id": {},
                }

            clustered, name_to_cluster = await cluster_candidates(all_pairs)
            build_session_id = state.get("build_session_id", "")
            if build_session_id:
                unified_session = get_unified_build_session(build_session_id)
                early_snapshot = _build_early_topic_snapshot(state, clustered)
                unified_session.publish_topic_anchor_snapshot(early_snapshot)

            update_job_progress(
                session,
                job_id=state["job_id"],
                job_type="graph",
                progress=50,
                current_step="cluster",
            )
            digest_logger.info(
                "kg_workflow_cluster_complete",
                input_candidates=len(all_pairs),
                cluster_count=len(clustered),
                early_topic_anchor_count=len(early_snapshot.anchors) if build_session_id else 0,
            )
            return {
                **state,
                "clustered_candidates": clustered,
                "candidate_name_to_cluster_id": name_to_cluster,
            }
        except Exception as exc:
            digest_logger.error("kg_workflow_cluster_failed", error=str(exc), exc_info=True)
            return {**state, "error": f"cluster_failed: {exc}"}


__all__ = [
    "acquire_lock_node",
    "cluster_node",
    "extract_node",
    "prepare_node",
]
