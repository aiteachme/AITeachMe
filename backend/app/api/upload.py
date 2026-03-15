"""
上传与文件状态端点

POST /api/v1/upload — 上传文件
GET  /api/v1/upload/{task_id}/status — 流水线聚合状态
GET  /api/v1/files/{subject} — 分页列表文件

需求：5.2, 5.3, 5.10, 5.11
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Form, Path, UploadFile, File
from sqlmodel import Session

from app.api.deps import get_db, validate_subject, PaginationParams
from app.core.exceptions import TaskNotFoundError
from app.repositories.ingest_repo import get_raw_file_by_id, list_raw_files_by_subject
from app.repositories.knowledge_repo import get_knowledge_by_raw_file_id
from app.schemas.upload import (
    UploadResponse,
    PipelineStatusResponse,
    FileItem,
    FileListResponse,
)
from app.services.upload_service import (
    handle_upload,
    process_and_parse,
    compute_pipeline_status,
)

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1", tags=["upload"])


async def _run_digest_background(knowledge_id: int, subject: str, markdown: str) -> None:
    """后台任务：运行 Digest 工作流。"""
    from app.ai.digest.workflow import run_digest_workflow

    try:
        await run_digest_workflow(
            knowledge_id=knowledge_id,
            subject=subject,
            raw_markdown=markdown,
        )
    except Exception as exc:
        logger.error("digest_background_error", knowledge_id=knowledge_id, error=str(exc))


@router.post("/upload", response_model=UploadResponse)
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    subject: str = Form(...),
    session: Session = Depends(get_db),
) -> UploadResponse:
    """上传文件，返回 task_id。Digest 引擎通过 BackgroundTasks 异步执行。"""
    raw_file = await handle_upload(session, file, subject)

    # 同步解析 + 异步触发 Digest
    knowledge = await process_and_parse(session, raw_file.id)  # type: ignore[arg-type]
    if knowledge is not None:
        md_path = raw_file.file_path  # 用于读取 markdown
        from pathlib import Path as P

        # 读取已保存的 markdown 文件
        from app.core.config import get_settings

        settings = get_settings()
        prefix = str(raw_file.id)[:2]
        md_file = P(settings.data_dir) / "markdown" / prefix / f"{raw_file.id}.md"
        markdown_text = md_file.read_text(encoding="utf-8") if md_file.exists() else ""

        background_tasks.add_task(
            _run_digest_background,
            knowledge_id=knowledge.id,  # type: ignore[arg-type]
            subject=knowledge.subject,
            markdown=markdown_text,
        )

    return UploadResponse(
        task_id=raw_file.id,  # type: ignore[arg-type]
        filename=raw_file.filename,
        subject=raw_file.subject,
    )


@router.get("/upload/{task_id}/status", response_model=PipelineStatusResponse)
async def get_pipeline_status(
    task_id: int = Path(...),
    session: Session = Depends(get_db),
) -> PipelineStatusResponse:
    """查询整个上传处理流水线的聚合状态。"""
    raw_file = get_raw_file_by_id(session, task_id)
    if raw_file is None:
        raise TaskNotFoundError(task_id)

    knowledge = get_knowledge_by_raw_file_id(session, task_id)
    status = compute_pipeline_status(raw_file, knowledge)
    return PipelineStatusResponse(**status)


@router.get("/files/{subject}", response_model=FileListResponse)
async def list_files(
    subject: str = Depends(validate_subject),
    pagination: PaginationParams = Depends(),
    session: Session = Depends(get_db),
) -> FileListResponse:
    """分页列表该学科所有已上传文件及其状态。"""
    items, total = list_raw_files_by_subject(
        session, subject, limit=pagination.limit, offset=pagination.offset
    )
    return FileListResponse(
        items=[
            FileItem(
                id=f.id,  # type: ignore[arg-type]
                filename=f.filename,
                filetype=f.filetype,
                parse_status=f.parse_status,
                created_at=f.created_at,
            )
            for f in items
        ],
        total=total,
    )
