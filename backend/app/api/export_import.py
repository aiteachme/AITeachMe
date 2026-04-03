"""学科导入导出 API。"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session

from app.api.deps import get_db
from app.api.openapi import build_error_responses
from app.schemas.common import ApiResponse, ok_response
from app.schemas.export_import import (
    CoursePackageItem,
    ExportOptions,
    ExportPreviewData,
    ImportOptions,
    ImportResultData,
)
from app.services.export_import_service import (
    export_subject,
    get_courses_dir_path,
    import_subject,
    list_available_courses,
    preview_export,
)

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
    session: Session = Depends(get_db),
) -> ApiResponse[ExportPreviewData]:
    """获取学科导出内容摘要。"""

    return ok_response(preview_export(session, subject_slug=subject))


@router.post(
    "/subjects/{subject}/export",
    summary="导出学科",
    responses=build_error_responses([404, 500]),
)
async def export_subject_api(
    subject: str,
    body: ExportOptions = Body(default=ExportOptions()),
    session: Session = Depends(get_db),
) -> FileResponse:
    """将学科全部产物打包为 .atmx 文件下载。"""

    tmp_path = export_subject(session, subject_slug=subject, options=body)
    filename = f"{subject}.atmx"
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
    session: Session = Depends(get_db),
) -> ApiResponse[ImportResultData]:
    """从上传的 .atmx 文件导入学科。"""

    suffix = Path(file.filename or "upload.atmx").suffix or ".atmx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        result = import_subject(
            session,
            file_path=tmp_path,
            options=ImportOptions(new_subject_name=new_subject_name),
        )
        return ok_response(result)
    finally:
        tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Shared courses folder
# ---------------------------------------------------------------------------


@router.get(
    "/courses",
    response_model=ApiResponse[list[CoursePackageItem]],
    summary="列出可导入课程",
    responses=build_error_responses([500]),
)
async def list_courses_api() -> ApiResponse[list[CoursePackageItem]]:
    """列出共享课程目录中的 .atmx 文件。"""

    return ok_response(list_available_courses())


@router.post(
    "/courses/{filename}/import",
    response_model=ApiResponse[ImportResultData],
    summary="从课程目录导入",
    responses=build_error_responses([400, 404, 500]),
)
async def import_course_api(
    filename: str,
    new_subject_name: str | None = Body(default=None, embed=True),
    session: Session = Depends(get_db),
) -> ApiResponse[ImportResultData]:
    """从共享课程目录导入指定 .atmx 文件。"""

    courses_dir = get_courses_dir_path()
    file_path = courses_dir / filename

    if not file_path.exists() or not file_path.is_file():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"课程文件不存在: {filename}")

    # 安全检查：防止路径遍历
    try:
        file_path.resolve().relative_to(courses_dir.resolve())
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="非法文件路径")

    result = import_subject(
        session,
        file_path=file_path,
        options=ImportOptions(new_subject_name=new_subject_name),
    )
    return ok_response(result)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cleanup_task(path: Path):
    """返回一个 Starlette BackgroundTask 在响应发送后清理临时文件。"""

    from starlette.background import BackgroundTask

    return BackgroundTask(lambda: path.unlink(missing_ok=True))
