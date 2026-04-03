"""Preparation and extraction nodes for the graph lane."""

from __future__ import annotations

import asyncio
from time import perf_counter

from sqlmodel import select

from app.shared.infra.config import get_settings
from app.shared.infra.database import managed_session
from app.models import RetrievalChunk
from app.repositories.knowledge import kg_repo
from app.utils.job_helpers import update_job_progress
from app.workflows.digest.kg.services.candidate_identity import candidate_lookup_keys
from app.workflows.digest.kg.services.clusterer import cluster_candidates
from app.workflows.digest.kg.services.extractor import (
    CandidateEdge,
    ChunkExtractionResult,
    extract_candidates,
    has_conceptual_content,
)
from app.workflows.digest.observability import add_slow_item
from app.workflows.digest.kg.state import KGDigestState
from app.workflows.digest.kg.support import workflow_logger
from app.workflows.common.runtime import cancel_tasks_and_drain
from app.workflows.digest.unified.models import ChapterPriors, TopicAnchor, TopicAnchorSnapshot
from app.workflows.digest.unified.session import get_unified_build_session

def _resolve_extract_parallelism(chunk_count: int = 0) -> int:
    settings = get_settings()
    ceiling = settings.llm_concurrency_limit
    configured = settings.kg_extract_max_parallelism
    # Adaptive: scale parallelism with chunk count so small jobs don't
    # over-subscribe and large jobs saturate the concurrency budget.
    if chunk_count <= 0:
        return max(1, min(configured, ceiling))
    if chunk_count <= 20:
        adaptive = min(chunk_count, 10)
    elif chunk_count <= 100:
        adaptive = min(chunk_count, 20)
    else:
        adaptive = min(chunk_count, 30)
    return max(1, min(adaptive, configured, ceiling))


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
        if not representative.name or representative.node_type not in {"Topic", "Concept", "Method"}:
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
            extract_parallelism = _resolve_extract_parallelism(len(chunk_ids))
            build_session_id = state.get("build_session_id", "")
            chapter_priors: ChapterPriors | None = None
            subject_context = ""
            shared_inputs = None
            digest_mode = ""
            sibling_topics = ""
            chapter_topic_hints: list[str] = []
            if build_session_id:
                unified_session = get_unified_build_session(build_session_id)
                shared_inputs = unified_session.shared_inputs
                settings = get_settings()
                chapter_priors = await unified_session.wait_for_chapter_priors(
                    timeout_ms=settings.digest_chapter_priors_timeout_ms
                )
                if unified_session.shared_inputs and unified_session.shared_inputs.subject_profile:
                    subject_context = unified_session.shared_inputs.subject_profile.build_context_string()
                # Resolve digest mode for prompt context
                if shared_inputs and shared_inputs.digest_mode_decision:
                    digest_mode = shared_inputs.digest_mode_decision.mode.value
                # Build sibling topics hint from chapter priors
                if chapter_priors:
                    all_terms: list[str] = []
                    for ch in chapter_priors.chapters:
                        chapter_topic_hints.append(ch.title)
                        chapter_topic_hints.extend(ch.section_titles[:3])
                        all_terms.extend(ch.key_terms[:3])
                    sibling_topics = "、".join(all_terms[:15])

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
            chunk_id_to_chunk_uid = state.get("chunk_id_to_chunk_uid", {})
            fast_path_chunk_count = 0
            llm_extract_chunk_count = 0
            slowest_chunks: list[dict[str, object]] = []

            def _should_prefer_fast_path(chunk_id: int) -> bool:
                if shared_inputs is None:
                    return False
                # Small material: never use fast path, always LLM extract
                if len(chunk_ids) < 20:
                    return False
                chunk_uid = chunk_id_to_chunk_uid.get(chunk_id)
                if not chunk_uid:
                    return False
                section_index = shared_inputs.chunk_identity_map.chunk_uid_to_section.get(chunk_uid)
                if section_index is None or section_index >= len(shared_inputs.section_packets):
                    return False
                section = shared_inputs.section_packets[section_index]
                # Only use fast path for chunks that are overwhelmingly
                # question-based (>= 3 question blocks) AND the material is
                # clearly an exam paper.  Mixed content (concepts + questions)
                # must go through LLM extraction to produce proper Concept /
                # Method nodes instead of only Example nodes.
                if section.question_block_count < 3:
                    return False
                # If the section contains conceptual content (definitions,
                # theorems, formula blocks, or significant non-question text),
                # it must go through LLM extraction even if question-heavy.
                if has_conceptual_content(section.normalized_content):
                    return False
                return (
                    shared_inputs.subject_profile.content_type == "exam_paper"
                    or shared_inputs.material_profile.stats.exercise_density >= 0.5
                )

            async def _extract_single(index: int, chunk_id: int):
                chunk = chunk_map.get(chunk_id)
                if chunk is None:
                    return index, chunk_id, ChunkExtractionResult(), [], "missing"

                try:
                    chunk_started_at = perf_counter()
                    used_fast_path = _should_prefer_fast_path(chunk_id)
                    async with semaphore:
                        result = await extract_candidates(
                            chunk_content=chunk.content,
                            chunk_title=chunk.title,
                            header_path=chunk.header_path,
                            doc_source_type=getattr(chunk, "source_type", None),
                            subject_context=subject_context,
                            prefer_fast_path=used_fast_path,
                            sibling_topics=sibling_topics,
                            digest_mode=digest_mode,
                            chapter_topic_hints=chapter_topic_hints,
                        )
                    _apply_taxonomy_hints(result, taxonomy_hints)
                    edge_payload = [(edge, chunk_id) for edge in result.edges]
                    return (
                        index,
                        chunk_id,
                        result,
                        edge_payload,
                        None,
                        int((perf_counter() - chunk_started_at) * 1000),
                        used_fast_path,
                    )
                except Exception as exc:
                    digest_logger.warning("kg_chunk_extraction_failed", chunk_id=chunk_id, error=str(exc))
                    return (
                        index,
                        chunk_id,
                        ChunkExtractionResult(),
                        [],
                        str(exc),
                        int((perf_counter() - chunk_started_at) * 1000),
                        False,
                    )

            tasks = [
                asyncio.create_task(_extract_single(index, chunk_id))
                for index, chunk_id in enumerate(chunk_ids)
            ]
            completed_count = 0
            try:
                for task in asyncio.as_completed(tasks):
                    index, chunk_id, result, edge_payload, error, chunk_elapsed_ms, used_fast_path = await task
                    ordered_results[index] = result
                    chunk_title = str(chunk_map.get(chunk_id).title) if chunk_map.get(chunk_id) is not None else f"chunk_{chunk_id}"
                    slowest_chunks = add_slow_item(
                        slowest_chunks,
                        item_id=str(chunk_id),
                        title=chunk_title,
                        elapsed_ms=chunk_elapsed_ms,
                        metadata={
                            "fast_path": used_fast_path,
                            "node_count": len(result.nodes),
                            "edge_count": len(result.edges),
                        },
                    )

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
                        if used_fast_path:
                            fast_path_chunk_count += 1
                        else:
                            llm_extract_chunk_count += 1

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
                        # Update runtime status with discovered node stats
                        total_nodes = sum(len(r.nodes) for r in ordered_results)
                        type_counts: dict[str, int] = {}
                        sample_nodes: list[dict[str, str]] = []
                        for r in ordered_results:
                            for n in r.nodes:
                                type_counts[n.node_type] = type_counts.get(n.node_type, 0) + 1
                                if len(sample_nodes) < 6 and n.node_type in ("Topic", "Concept", "Method"):
                                    sample_nodes.append({"name": n.name, "type": n.node_type})
                        try:
                            from app.utils.docgen_store import update_knowledge_build_status
                            update_knowledge_build_status(
                                state["subject"],
                                progress_pct=min(progress, 40),
                                discovered_node_count=total_nodes,
                                discovered_node_types=type_counts,
                                sample_nodes=sample_nodes,
                                processed_chunks=completed_count,
                                total_chunks=len(chunk_ids),
                                current_chunk=completed_count,
                            )
                        except Exception:
                            pass  # non-critical
            except asyncio.CancelledError:
                await cancel_tasks_and_drain(tasks)
                raise

            update_job_progress(
                session,
                job_id=state["job_id"],
                job_type="graph",
                progress=40,
                current_step="extract",
            )
            try:
                from app.utils.docgen_store import update_knowledge_build_status

                update_knowledge_build_status(
                    state["subject"],
                    progress_pct=40,
                    processed_chunks=len(chunk_ids),
                    total_chunks=len(chunk_ids),
                    current_chunk=len(chunk_ids),
                )
            except Exception:
                pass
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
                "fast_path_chunk_count": fast_path_chunk_count,
                "llm_extract_chunk_count": llm_extract_chunk_count,
                "success_chunk_count": success_chunk_count,
                "failed_chunk_count": failed_chunk_count,
                "slowest_chunks": slowest_chunks,
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
                    "candidate_lookup_to_cluster_id": {},
                }

            clustered, lookup_to_cluster = await cluster_candidates(all_pairs)
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
                "candidate_lookup_to_cluster_id": lookup_to_cluster,
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
