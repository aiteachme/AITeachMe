"""Upload, file listing, and pipeline progress routes."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Form, Path, UploadFile
from sqlmodel import Session

from app.api.docs import build_error_responses
from app.api.deps import get_db, validate_subject, PaginationParams
from app.core.exceptions import TaskNotFoundError
from app.repositories.ingest_repo import get_raw_file_by_id, list_raw_files_by_subject
from app.repositories.knowledge_repo import get_knowledge_by_raw_file_id
from app.schemas.upload import (
    FileListResponse,
    PipelineStatusResponse,
    UploadResponse,
)
from app.services.upload_service import (
    handle_upload,
    process_and_parse,
)
from app.services.upload_support import build_markdown_path, build_pipeline_status
from app.services.presenters import require_id, to_file_list_response

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1", tags=["upload"])


async def _run_digest_background(knowledge_id: int, subject: str, markdown: str) -> None:
    """Run the digest workflow in a background task after parsing completes."""
    from app.agents.digest.workflow import run_digest_workflow

    try:
        await run_digest_workflow(
            knowledge_id=knowledge_id,
            subject=subject,
            raw_markdown=markdown,
        )
    except Exception as exc:
        logger.error("digest_background_error", knowledge_id=knowledge_id, error=str(exc))


@router.post(
    "/upload",
    response_model=UploadResponse,
    summary="上传学习资料",
    description="接收一个文件并同步完成落盘与解析，然后通过后台任务触发 Digest 消化索引流程。",
    response_description="已受理的上传任务信息。",
    responses=build_error_responses([400, 413, 422, 500]),
)
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="待上传的学习资料文件，如 PDF、PPT 或图片。"),
    subject: str = Form(..., description="学科标识，仅允许字母、数字、下划线和连字符。"),
    session: Session = Depends(get_db),
) -> UploadResponse:
    """Accept an uploaded file and schedule digest processing in the background."""
    raw_file = await handle_upload(session, file, subject)
    raw_file_id = require_id(raw_file.id, "RawFile.id")

    # 同步解析 + 异步触发 Digest
    knowledge = await process_and_parse(session, raw_file_id)
    if knowledge is not None:
        knowledge_id = require_id(knowledge.id, "Knowledge.id")
        md_file = build_markdown_path(raw_file_id)
        markdown_text = md_file.read_text(encoding="utf-8") if md_file.exists() else ""

        background_tasks.add_task(
            _run_digest_background,
            knowledge_id=knowledge_id,
            subject=knowledge.subject,
            markdown=markdown_text,
        )

    return UploadResponse(
        task_id=raw_file_id,
        filename=raw_file.filename,
        subject=raw_file.subject,
    )


@router.post(
    "/upload/{task_id}/status",
    response_model=PipelineStatusResponse,
    summary="查询上传任务状态",
    description="返回上传、解析与 Digest 三段流程聚合后的当前进度，适合前端轮询展示。",
    response_description="任务聚合状态。",
    responses=build_error_responses([404, 500]),
)
async def get_pipeline_status(
    task_id: int = Path(..., description="上传任务 ID，即 RawFile 记录 ID。", examples=[42]),
    session: Session = Depends(get_db),
) -> PipelineStatusResponse:
    """Return the aggregated status for one uploaded file processing task."""
    raw_file = get_raw_file_by_id(session, task_id)
    if raw_file is None:
        raise TaskNotFoundError(task_id)

    knowledge = get_knowledge_by_raw_file_id(session, task_id)
    return build_pipeline_status(raw_file, knowledge)


@router.post(
    "/files/{subject}",
    response_model=FileListResponse,
    summary="列出学科文件",
    description="分页返回指定学科下的全部上传文件及其解析状态。",
    response_description="文件分页列表。",
    responses=build_error_responses([400, 500]),
)
async def list_files(
    body: PaginationParams = Body(..., description="分页参数。"),
    subject: str = Depends(validate_subject),
    session: Session = Depends(get_db),
) -> FileListResponse:
    """Return a paginated list of uploaded files for one subject."""
    items, total = list_raw_files_by_subject(
        session, subject, limit=body.limit, offset=body.offset
    )
    return to_file_list_response(items, total)
