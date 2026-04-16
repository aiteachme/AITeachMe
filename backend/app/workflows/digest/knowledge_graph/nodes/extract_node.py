"""Knowledge graph extract node."""


from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Any

from sqlmodel import select

from app.shared.infra.settings import get_settings
from app.shared.infra.database import managed_session
from app.models import RetrievalChunk
from app.utils.job_helpers import update_job_progress
from app.workflows.digest.knowledge_graph.lib.extractor import (
    CandidateEdge,
    ChunkExtractionResult,
    extract_candidates,
    has_conceptual_content,
)
from app.workflows.digest.common.metrics import add_slow_item
from app.workflows.digest.knowledge_graph.state import KGDigestState
from app.workflows.digest.knowledge_graph.support import workflow_logger
from app.shared.infra.workflow.runtime import cancel_tasks_and_drain

def _resolve_extract_parallelism(chunk_count: int = 0) -> int:
    settings = get_settings()
    ceiling = settings.runtime.llm_concurrency_limit
    configured = settings.knowledge_graph.extract_max_parallelism
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


def _build_taxonomy_hints(shared_inputs: Any | None) -> set[str]:
    if shared_inputs is None:
        return set()

    hints: set[str] = set()
    subject_profile = getattr(shared_inputs, "subject_profile", None)
    fast_hints = getattr(shared_inputs, "fast_hints", None)
    hints.update(getattr(subject_profile, "key_topics", []) or [])
    hints.update(getattr(fast_hints, "chapter_candidates", []) or [])
    hints.update(term for term, _count in (getattr(fast_hints, "high_freq_terms", []) or []))
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


async def extract_node(state: KGDigestState) -> KGDigestState:
    """Extract candidate nodes and edges chunk by chunk with controlled parallelism."""

    with managed_session() as session:
        digest_logger = workflow_logger(state)
        try:
            chunk_ids = list(state.get("chunk_ids", []))
            extract_parallelism = _resolve_extract_parallelism(len(chunk_ids))
            subject_context = ""
            shared_inputs = state.get("shared_inputs")
            digest_mode = ""
            sibling_topics = ""
            chapter_topic_hints: list[str] = []
            if shared_inputs is not None:
                if getattr(shared_inputs, "subject_profile", None):
                    subject_context = shared_inputs.subject_profile.build_context_string()
                    chapter_topic_hints.extend(list(shared_inputs.subject_profile.key_topics[:8]))
                if getattr(shared_inputs, "fast_hints", None):
                    chapter_topic_hints.extend(list(shared_inputs.fast_hints.chapter_candidates[:8]))
                    sibling_topics = "、".join(
                        [
                            str(term)
                            for term, _count in list(shared_inputs.fast_hints.high_freq_terms[:15])
                            if str(term).strip()
                        ]
                    )
                if getattr(shared_inputs, "digest_mode_decision", None):
                    digest_mode = shared_inputs.digest_mode_decision.mode.value

            taxonomy_hints = _build_taxonomy_hints(shared_inputs)
            digest_logger.info(
                "kg_extract_started",
                chunk_count=len(chunk_ids),
                parallelism=extract_parallelism,
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
            chunk_id_to_index = {chunk_id: index for index, chunk_id in enumerate(chunk_ids)}
            file_id_to_chunk_ids: dict[int, list[int]] = {}
            for chunk_id, chunk in chunk_map.items():
                file_id_to_chunk_ids.setdefault(int(chunk.document_id), []).append(chunk_id)
            for ids in file_id_to_chunk_ids.values():
                ids.sort()
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

__all__ = ["extract_node"]

