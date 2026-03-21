"""Preparation-phase nodes for the digest graph workflow."""

from __future__ import annotations

from sqlmodel import select

from app.workflows.digest.kg.services.clusterer import cluster_candidates
from app.workflows.digest.kg.services.extractor import (
    CandidateEdge,
    ChunkExtractionResult,
    extract_candidates,
)
from app.core.database import managed_session
from app.models import RawFile
from app.models.knowledge import DocumentChunk
from app.repositories import kg_repo
from app.utils.job_helpers import update_job_progress
from app.workflows.digest.kg.state import KGDigestState
from app.workflows.digest.kg.support import prepare_chunk_ids_for_files, workflow_logger


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
    """Load or materialize digest-ready chunks for the target files."""

    with managed_session() as session:
        digest_logger = workflow_logger(state)
        try:
            file_ids = state["file_ids"]
            digest_logger.info("kg_prepare_started")
            raw_files = session.exec(
                select(RawFile).where(
                    RawFile.subject == state["subject"],
                    RawFile.id.in_(file_ids),  # type: ignore[union-attr]
                )
            ).all()
            document_ids, chunk_ids = await prepare_chunk_ids_for_files(
                session,
                raw_files=list(raw_files),
                digest_logger=digest_logger,
            )
            if not chunk_ids:
                digest_logger.warning(
                    "kg_workflow_no_digest_inputs",
                    raw_file_count=len(raw_files),
                    raw_files=[
                        {
                            "file_id": raw_file.id,
                            "status": raw_file.status,
                            "ingest_status": raw_file.ingest_status,
                            "markdown_ready": bool(raw_file.markdown_path),
                            "filename": raw_file.filename,
                        }
                        for raw_file in raw_files
                    ],
                )
                return {**state, "error": "no_ready_digest_inputs"}

            kg_repo.update_digest_job(
                session,
                state["job_id"],
                input_chunk_count=len(chunk_ids),
            )
            update_job_progress(
                session,
                job_id=state["job_id"],
                job_type="graph",
                progress=10,
                current_step="prepare",
            )

            digest_logger.info(
                "kg_workflow_prepare_complete",
                document_ids=document_ids,
                source_file_ids=[raw_file.id for raw_file in raw_files if raw_file.id is not None],
                document_count=len(document_ids),
                chunk_count=len(chunk_ids),
            )
            return {**state, "chunk_ids": chunk_ids}
        except Exception as exc:
            digest_logger.error("kg_workflow_prepare_failed", error=str(exc), exc_info=True)
            return {**state, "error": f"prepare_failed: {exc}"}


async def extract_node(state: KGDigestState) -> KGDigestState:
    """Extract candidate nodes and edges chunk by chunk."""

    with managed_session() as session:
        digest_logger = workflow_logger(state)
        try:
            chunk_ids = state.get("chunk_ids", [])
            digest_logger.info("kg_extract_started", chunk_count=len(chunk_ids))
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

            chunks = session.exec(
                select(DocumentChunk).where(
                    DocumentChunk.id.in_(chunk_ids),  # type: ignore[union-attr]
                )
            ).all()
            chunk_map = {chunk.id: chunk for chunk in chunks}

            all_results: list[ChunkExtractionResult] = []
            all_candidate_edges: list[tuple[CandidateEdge, int]] = []
            success_chunk_count = 0
            failed_chunk_count = 0

            for index, chunk_id in enumerate(chunk_ids):
                chunk = chunk_map.get(chunk_id)
                if chunk is None:
                    failed_chunk_count += 1
                    digest_logger.warning("kg_extract_chunk_missing", chunk_id=chunk_id)
                    continue

                try:
                    result = await extract_candidates(
                        chunk_content=chunk.content,
                        chunk_title=chunk.title,
                        header_path=chunk.header_path,
                    )
                    all_results.append(result)
                    success_chunk_count += 1
                    for edge in result.edges:
                        all_candidate_edges.append((edge, chunk_id))
                except Exception as exc:
                    failed_chunk_count += 1
                    digest_logger.warning(
                        "kg_extract_chunk_failed",
                        chunk_id=chunk_id,
                        error=str(exc),
                    )
                    continue

                if (index + 1) % 10 == 0:
                    progress = 10 + int(30 * (index + 1) / len(chunk_ids))
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

            digest_logger.info(
                "kg_workflow_extract_complete",
                total_chunks=len(chunk_ids),
                success_chunk_count=success_chunk_count,
                failed_chunk_count=failed_chunk_count,
                results_count=len(all_results),
                total_nodes=sum(len(result.nodes) for result in all_results),
                total_edges=len(all_candidate_edges),
            )
            return {
                **state,
                "candidates": all_results,
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

            all_pairs: list[tuple] = []
            result_index = 0
            for chunk_id in chunk_ids:
                if result_index >= len(results):
                    break
                result = results[result_index]
                for node in result.nodes:
                    all_pairs.append((node, chunk_id))
                result_index += 1

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
