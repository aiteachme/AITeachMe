"""消化构建服务层：触发增量构建、后台执行、状态查询。"""

from __future__ import annotations

import hashlib
import json
import traceback

import structlog
from sqlmodel import Session, select

from app.agents.digest.curriculum_workflow import (
    CurriculumDeriveState,
    build_curriculum_derive_graph,
)
from app.agents.digest.kg_workflow import KGDigestState, build_kg_digest_graph
from app.core.database import managed_session
from app.core.exceptions import (
    DigestJobNotFoundError,
    SubjectBuildLockConflictError,
)
from app.models.curriculum import CurriculumDeriveJob, CurriculumSnapshot
from app.models.knowledge_graph import GraphDigestJob
from app.repositories import curriculum_repo, kg_repo
from app.schemas.knowledge import (
    CurriculumJobResponse,
    DigestBuildData,
    DigestStatusResponse,
    GraphDigestJobResponse,
)

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# 幂等键生成
# ---------------------------------------------------------------------------


def _compute_idempotency_key(subject: str, file_ids: list[int]) -> str:
    """基于 subject + 排序后 file_ids 计算幂等键。"""
    sorted_ids = sorted(file_ids)
    raw = f"{subject}:{json.dumps(sorted_ids)}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# 触发增量构建
# ---------------------------------------------------------------------------


def trigger_digest_build(
    session: Session,
    *,
    subject: str,
    file_ids: list[int],
    idempotency_key: str | None = None,
) -> DigestBuildData:
    """触发增量构建：三层检查（幂等键命中 → 运行中冲突 → 创建新 job）。

    不在此处获取构建锁，锁由工作流 acquire_lock_node 获取。
    """
    key = idempotency_key or _compute_idempotency_key(subject, file_ids)
    digest_logger = logger.bind(
        subject=subject,
        file_ids=file_ids,
        idempotency_key=key,
    )
    digest_logger.info("digest_build_requested")

    # 1) 幂等键命中 → 返回已有 job
    existing = kg_repo.find_job_by_idempotency_key(session, key)
    if existing is not None:
        digest_logger.info(
            "digest_build_existing_job_reused",
            existing_job_id=existing.id,
            existing_status=existing.status,
        )
        return DigestBuildData(
            job_id=existing.id,  # type: ignore[arg-type]
            is_existing=True,
        )

    # 2) 同 subject 是否有运行中的 job → 409
    running = session.exec(
        select(GraphDigestJob).where(
            GraphDigestJob.subject == subject,
            GraphDigestJob.status == "processing",
        )
    ).first()
    if running is not None:
        digest_logger.warning(
            "digest_build_conflict",
            running_job_id=running.id,
            running_status=running.status,
        )
        raise SubjectBuildLockConflictError(subject)

    # 3) 创建新 job
    job = kg_repo.create_digest_job(
        session,
        GraphDigestJob(
            subject=subject,
            idempotency_key=key,
            status="pending",
            input_file_ids_json=json.dumps(sorted(file_ids)),
        ),
    )
    digest_logger.info("digest_build_job_created", job_id=job.id)
    return DigestBuildData(job_id=job.id, is_existing=False)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 后台执行图谱构建
# ---------------------------------------------------------------------------


async def run_graph_digest_background(*, subject: str, job_id: int) -> None:
    """后台异步执行 GraphDigestJob 工作流。"""
    with managed_session() as session:
        try:
            job = session.get(GraphDigestJob, job_id)
            if job is None:
                logger.error("graph_digest_job_not_found", job_id=job_id)
                return

            # 解析 file_ids
            file_ids: list[int] = json.loads(job.input_file_ids_json or "[]")
            digest_logger = logger.bind(subject=subject, job_id=job_id, file_ids=file_ids)
            digest_logger.info(
                "graph_digest_background_started",
                job_status=job.status,
                progress=job.progress,
            )

            # 构建初始状态
            initial_state: KGDigestState = {
                "subject": subject,
                "file_ids": file_ids,
                "job_id": job_id,
                "chunk_ids": [],
                "candidates": [],
                "all_candidate_edges": [],
                "clustered_candidates": [],
                "candidate_name_to_cluster_id": {},
                "candidate_name_to_resolved_node_id": {},
                "cluster_id_to_resolved_node_id": {},
                "new_node_ids": [],
                "updated_node_ids": [],
                "merged_node_ids": [],
                "new_edge_ids": [],
                "updated_edge_ids": [],
                "impact_set": None,
                "lock_acquired": False,
                "error": None,
            }

            graph = build_kg_digest_graph()
            compiled = graph.compile()
            await compiled.ainvoke(initial_state)
            final_job = session.get(GraphDigestJob, job_id)
            digest_logger.info(
                "graph_digest_background_completed",
                final_status=final_job.status if final_job is not None else None,
                final_progress=final_job.progress if final_job is not None else None,
                final_step=final_job.current_step if final_job is not None else None,
                input_chunk_count=final_job.input_chunk_count if final_job is not None else None,
            )

        except Exception:
            logger.exception(
                "graph_digest_background_error",
                subject=subject,
                job_id=job_id,
            )
            # 尝试标记 job 为 failed
            try:
                kg_repo.update_digest_job(
                    session,
                    job_id,
                    status="failed",
                    error_message=traceback.format_exc()[-500:],
                )
            except Exception:
                logger.exception("failed_to_mark_job_failed", job_id=job_id)


# ---------------------------------------------------------------------------
# 后台执行课程派生
# ---------------------------------------------------------------------------


async def run_curriculum_derive_background(
    *, subject: str, graph_job_id: int, curriculum_job_id: int
) -> None:
    """后台异步执行 CurriculumDeriveJob 工作流。"""
    with managed_session() as session:
        try:
            graph_job = session.get(GraphDigestJob, graph_job_id)
            if graph_job is None:
                logger.error("graph_job_not_found_for_curriculum", graph_job_id=graph_job_id)
                return

            graph = build_curriculum_derive_graph()
            compiled = graph.compile()

            initial_state: CurriculumDeriveState = {
                "subject": subject,
                "graph_job_id": graph_job_id,
                "curriculum_job_id": curriculum_job_id,
                "impact_set": None,
                "derived_unit_ids": [],
                "theme_tree_version_id": None,
                "prereq_dag_version_id": None,
                "snapshot_id": None,
                "error": None,
            }

            await compiled.ainvoke(initial_state)

        except Exception:
            logger.exception(
                "curriculum_derive_background_error",
                curriculum_job_id=curriculum_job_id,
            )
            try:
                curriculum_repo.update_curriculum_job(
                    session,
                    curriculum_job_id,
                    status="failed",
                    error_message=traceback.format_exc()[-500:],
                )
            except Exception:
                logger.exception("failed_to_mark_curriculum_job_failed")


# ---------------------------------------------------------------------------
# 状态查询
# ---------------------------------------------------------------------------


def _build_graph_job_response(job: GraphDigestJob) -> GraphDigestJobResponse:
    return GraphDigestJobResponse(
        id=job.id,  # type: ignore[arg-type]
        subject=job.subject,
        status=job.status,
        progress=job.progress,
        current_step=job.current_step,
        input_chunk_count=job.input_chunk_count,
        nodes_added=job.nodes_added,
        nodes_updated=job.nodes_updated,
        nodes_merged=job.nodes_merged,
        edges_added=job.edges_added,
        edges_updated=job.edges_updated,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _build_curriculum_job_response(
    job: CurriculumDeriveJob,
) -> CurriculumJobResponse:
    return CurriculumJobResponse(
        id=job.id,  # type: ignore[arg-type]
        subject=job.subject,
        graph_job_id=job.graph_job_id,
        status=job.status,
        progress=job.progress,
        current_step=job.current_step,
        units_added=job.units_added,
        units_updated=job.units_updated,
        theme_tree_version_id=job.theme_tree_version_id,
        prereq_dag_version_id=job.prereq_dag_version_id,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def get_digest_status(
    session: Session, *, subject: str, job_id: int
) -> DigestStatusResponse:
    """聚合查询：GraphDigestJob + 关联 CurriculumDeriveJob + 当前快照 ID。"""
    job = session.get(GraphDigestJob, job_id)
    if job is None or job.subject != subject:
        raise DigestJobNotFoundError(job_id)

    graph_resp = _build_graph_job_response(job)

    curriculum_resp: CurriculumJobResponse | None = None
    if job.curriculum_job_id is not None:
        cjob = session.get(CurriculumDeriveJob, job.curriculum_job_id)
        if cjob is not None:
            curriculum_resp = _build_curriculum_job_response(cjob)

    snapshot = session.exec(
        select(CurriculumSnapshot).where(
            CurriculumSnapshot.subject == subject,
            CurriculumSnapshot.status == "published",
        )
    ).first()
    snapshot_id = snapshot.id if snapshot is not None else None

    logger.info(
        "digest_status_loaded",
        subject=subject,
        job_id=job_id,
        graph_status=job.status,
        graph_progress=job.progress,
        graph_step=job.current_step,
        input_chunk_count=job.input_chunk_count,
        curriculum_job_id=job.curriculum_job_id,
        curriculum_status=curriculum_resp.status if curriculum_resp is not None else None,
        snapshot_id=snapshot_id,
    )

    return DigestStatusResponse(
        graph_job=graph_resp,
        curriculum_job=curriculum_resp,
        current_curriculum_snapshot_id=snapshot_id,
    )
