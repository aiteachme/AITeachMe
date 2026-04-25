"""学科导入导出 API。"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session

from app.api.deps import CurrentUserContext, get_current_user_context, get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.schemas.common import ApiResponse, ok_response
from app.schemas.export_import import (
    CoursePackageItem,
    ExportOptions,
    ExportPreviewData,
    ImportOptions,
    ImportResultData,
)
from app.workflows.support.export_import import (
    download_course_package,
    export_subject,
    import_subject,
    list_available_courses,
    preview_export,
)
from app.workflows.support.subjects import get_subject_record

router = APIRouter(prefix="/api/v1", tags=["export-import"])


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


@router.post(
    "/subjects/{subject}/export/preview",
    response_model=ApiResponse[ExportPreviewData],
    summary="导出预览",
    responses=build_error_responses([404, 500]),
)
async def export_preview_api(
    subject: str,
    body: ExportOptions = Body(default=ExportOptions()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExportPreviewData]:
    """获取学科导出内容摘要。"""

    normalized = normalize_subject_slug(subject)
    subject_record = get_subject_record(session, normalized, owner_user_id=user.user_id)
    return ok_response(preview_export(session, subject_slug=subject_record.slug, options=body))


@router.post(
    "/subjects/{subject}/export",
    summary="导出学科",
    responses=build_error_responses([404, 500]),
)
async def export_subject_api(
    subject: str,
    body: ExportOptions = Body(default=ExportOptions()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> FileResponse:
    """将学科全部产物打包为 .atmx 文件下载。"""

    normalized = normalize_subject_slug(subject)
    subject_record = get_subject_record(session, normalized, owner_user_id=user.user_id)
    tmp_path = export_subject(session, subject_slug=subject_record.slug, options=body)
    filename = f"{subject_record.slug}.atmx"
    return FileResponse(
        path=tmp_path,
        media_type="application/octet-stream",
        filename=filename,
        background=_cleanup_task(tmp_path),
    )


# ---------------------------------------------------------------------------
# Import (upload)
# ---------------------------------------------------------------------------


@router.post(
    "/subjects/import",
    response_model=ApiResponse[ImportResultData],
    summary="导入学科（上传）",
    responses=build_error_responses([400, 409, 500]),
)
async def import_subject_api(
    file: UploadFile = File(..., description="上传 .atmx 导出包。"),
    new_subject_name: str | None = Form(default=None, description="自定义导入学科名。"),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ImportResultData]:
    """从上传的 .atmx 文件导入学科。"""

    suffix = Path(file.filename or "upload.atmx").suffix or ".atmx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        result = import_subject(
            session,
            file_path=tmp_path,
            options=ImportOptions(new_subject_name=new_subject_name),
            user_id=user.user_id,
        )
        return ok_response(result)
    finally:
        tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Demo courses catalog
# ---------------------------------------------------------------------------


@router.get(
    "/courses",
    response_model=ApiResponse[list[CoursePackageItem]],
    summary="列出可导入课程",
    responses=build_error_responses([500, 502]),
)
async def list_courses_api() -> ApiResponse[list[CoursePackageItem]]:
    """列出线上演示课程目录中的课程包。"""

    return ok_response(list_available_courses())


@router.post(
    "/courses/{filename}/import",
    response_model=ApiResponse[ImportResultData],
    summary="从演示课程导入",
    responses=build_error_responses([404, 500, 502, 503]),
)
async def import_course_api(
    filename: str,
    new_subject_name: str | None = Body(default=None, embed=True),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ImportResultData]:
    """从线上演示课程目录下载 `.atmx` 后导入。"""

    tmp_path, _download_name = download_course_package(filename)
    try:
        result = import_subject(
            session,
            file_path=tmp_path,
            options=ImportOptions(new_subject_name=new_subject_name),
            user_id=user.user_id,
        )
        return ok_response(result)
    finally:
        tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cleanup_task(path: Path):
    """返回一个 Starlette BackgroundTask 在响应发送后清理临时文件。"""

    from starlette.background import BackgroundTask

    return BackgroundTask(lambda: path.unlink(missing_ok=True))
