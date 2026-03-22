"""消化构建服务层：触发增量构建、后台执行、状态查询。"""

from __future__ import annotations

import json
import shutil
import traceback
import uuid
from datetime import datetime
from pathlib import Path

import structlog
from sqlmodel import Session, select

from app.core.database import managed_session
from app.core.exceptions import (
    DigestJobNotFoundError,
    NoReadyFilesForDocGenError,
    RawFileNotFoundError,
    SubjectBuildLockConflictError,
)
from app.models.curriculum import CurriculumDeriveJob, CurriculumSnapshot
from app.models.knowledge_graph import GraphDigestJob
from app.models.raw_file import RawFile
from app.repositories import curriculum_repo, kg_repo
from app.repositories.files_repo import list_all_raw_files_by_subject, list_raw_files_by_ids
from app.repositories.knowledge import docgen_repo
from app.schemas.knowledge import (
    CurriculumJobResponse,
    DigestBuildData,
    DocGenBuildData,
    DocGenGetResponse,
    DocGenJobResponse,
    DigestStatusResponse,
    GraphDigestJobResponse,
)
from app.services.upload_support import (
    build_docgen_intermediate_dir,
    build_knowledge_docs_dir,
    build_merged_knowledge_base_path,
)
from app.workflows.digest import run_curriculum_derive_workflow, run_graph_digest_workflow

logger = structlog.get_logger()


def _parse_json_int_list(payload: str | None) -> list[int]:
    if not payload:
        return []
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    return [int(item) for item in raw if isinstance(item, (int, str)) and str(item).isdigit()]


def _markdown_ready(raw_file: RawFile) -> bool:
    return bool(raw_file.markdown_path and Path(raw_file.markdown_path).exists())


def _build_docgen_job_response(job) -> DocGenJobResponse:
    return DocGenJobResponse.model_validate(job)


def _collect_published_doc_source_ids(session: Session, subject: str) -> list[int]:
    source_file_ids: set[int] = set()
    for doc in docgen_repo.get_docs_by_subject(session, subject, status="published"):
        source_file_ids.update(_parse_json_int_list(doc.source_file_ids))
    return sorted(source_file_ids)


def _select_ready_docgen_file_ids(
    session: Session,
    *,
    subject: str,
    file_ids: list[int] | None,
) -> tuple[list[int], int]:
    all_files = list_all_raw_files_by_subject(session, subject)
    ready_file_ids = [raw_file.id for raw_file in all_files if raw_file.id is not None and _markdown_ready(raw_file)]
    ready_file_count = len(ready_file_ids)

    if file_ids is None:
        accepted = ready_file_ids
    else:
        requested_items = list_raw_files_by_ids(session, subject, file_ids)
        found_ids = {item.id for item in requested_items if item.id is not None}
        missing_ids = [file_id for file_id in file_ids if file_id not in found_ids]
        if missing_ids:
            raise RawFileNotFoundError(missing_ids[0])
        ready_set = set(ready_file_ids)
        accepted = [file_id for file_id in file_ids if file_id in ready_set]

    if not accepted:
        raise NoReadyFilesForDocGenError(subject)

    return accepted, ready_file_count


def _reset_docgen_outputs(session: Session, *, subject: str) -> None:
    docgen_repo.delete_docs_by_subject(session, subject)
    for directory in (build_knowledge_docs_dir(subject), build_docgen_intermediate_dir(subject)):
        if directory.exists():
            shutil.rmtree(directory, ignore_errors=True)


# ---------------------------------------------------------------------------
# 幂等键生成
# ---------------------------------------------------------------------------


def _compute_idempotency_key(subject: str, file_ids: list[int]) -> str:
    """开发阶段默认生成一次性幂等键，避免复用历史空任务。"""

    del file_ids
    return f"{subject}:{uuid.uuid4().hex}"


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
            )
            result = await run_graph_digest_workflow(
                subject=subject,
                job_id=job_id,
                file_ids=file_ids,
            )
            if result.failed:
                kg_repo.update_digest_job(
                    session,
                    job_id,
                    status="failed",
                    error_message=result.error.detail[-500:],
                )
            final_job = session.get(GraphDigestJob, job_id)
            digest_logger.info(
                "graph_digest_background_completed",
                final_status=final_job.status if final_job is not None else None,
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
            result = await run_curriculum_derive_workflow(
                subject=subject,
                graph_job_id=graph_job_id,
                curriculum_job_id=curriculum_job_id,
            )
            if result.failed:
                curriculum_repo.update_curriculum_job(
                    session,
                    curriculum_job_id,
                    status="failed",
                    error_message=result.error.detail[-500:],
                )

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


# ---------------------------------------------------------------------------
# DocGen 知识文档生成
# ---------------------------------------------------------------------------


def trigger_docgen_build(
    session: Session,
    *,
    subject: str,
    file_ids: list[int] | None,
    prompt: str | None,
) -> DocGenBuildData:
    """创建 DocGen 任务并返回聚合构建信息。"""

    from app.models.knowledge_doc import DocGenJob

    accepted_file_ids, ready_file_count = _select_ready_docgen_file_ids(
        session,
        subject=subject,
        file_ids=file_ids,
    )
    _reset_docgen_outputs(session, subject=subject)
    job = docgen_repo.create_docgen_job(
        session,
        DocGenJob(
            subject=subject,
            status="pending",
            input_file_ids_json=json.dumps(sorted(accepted_file_ids)),
            user_prompt=(prompt or "").strip() or None,
        ),
    )
    logger.info(
        "docgen_build_triggered",
        subject=subject,
        job_id=job.id,
        accepted_file_ids=accepted_file_ids,
        ready_file_count=ready_file_count,
        has_prompt=bool(prompt and prompt.strip()),
    )
    return DocGenBuildData(
        job_id=job.id,  # type: ignore[arg-type]
        accepted_file_ids=accepted_file_ids,
        prompt=(prompt or "").strip() or None,
        ready_file_count=ready_file_count,
    )


async def run_docgen_background(*, subject: str, job_id: int) -> None:
    """后台异步执行 DocGen 工作流。"""

    from app.models.knowledge_doc import DocGenJob
    from app.workflows.digest import run_docgen_workflow

    with managed_session() as session:
        try:
            job = session.get(DocGenJob, job_id)
            if job is None:
                logger.error("docgen_job_not_found", job_id=job_id)
                return

            file_ids: list[int] = json.loads(job.input_file_ids_json or "[]")
            docgen_logger = logger.bind(subject=subject, job_id=job_id, file_ids=file_ids)
            docgen_logger.info("docgen_background_started")

            # 标记为 processing
            docgen_repo.update_docgen_job(session, job_id, status="processing")

            result = await run_docgen_workflow(
                subject=subject,
                job_id=job_id,
                file_ids=file_ids,
                user_prompt=job.user_prompt,
            )
            if result.failed:
                docgen_repo.update_docgen_job(
                    session, job_id,
                    status="failed",
                    error_message=result.error.detail[-500:],
                )
            docgen_logger.info(
                "docgen_background_completed",
                success=result.ok,
            )

        except Exception:
            logger.exception("docgen_background_error", subject=subject, job_id=job_id)
            try:
                docgen_repo.update_docgen_job(
                    session, job_id,
                    status="failed",
                    error_message=traceback.format_exc()[-500:],
                )
            except Exception:
                logger.exception("failed_to_mark_docgen_job_failed", job_id=job_id)


def get_docgen_result(session: Session, *, subject: str) -> DocGenGetResponse:
    """聚合读取知识文档最终结果与最近任务状态。"""

    merged_path = build_merged_knowledge_base_path(subject)
    latest_job = docgen_repo.get_latest_docgen_job_by_subject(session, subject)
    job_response = _build_docgen_job_response(latest_job) if latest_job is not None else None
    prompt = latest_job.user_prompt if latest_job is not None else None
    source_file_ids = (
        _collect_published_doc_source_ids(session, subject)
        if merged_path.exists()
        else _parse_json_int_list(latest_job.input_file_ids_json if latest_job is not None else None)
    )

    if merged_path.exists():
        return DocGenGetResponse(
            exists=True,
            markdown=merged_path.read_text(encoding="utf-8"),
            merged_path=str(merged_path),
            updated_at=datetime.fromtimestamp(merged_path.stat().st_mtime),
            job=job_response,
            source_file_ids=source_file_ids,
            prompt=prompt,
        )

    return DocGenGetResponse(
        exists=False,
        markdown="",
        merged_path=str(merged_path),
        updated_at=None,
        job=job_response,
        source_file_ids=source_file_ids,
        prompt=prompt,
    )
