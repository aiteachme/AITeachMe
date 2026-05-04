"""课程导入导出 API。"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, Form, Path, Response, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUserContext, get_current_user_context, get_db, normalize_course_id
from app.api.openapi import build_error_responses
from app.schemas.common import ApiResponse, ok_response
from app.schemas.export_import import (
    CoursePackageItem,
    ExportOptions,
    ExportPreviewData,
    ImportOptions,
    ImportResultData,
)
from app.shared.infra.exceptions import ImportPackageTooLargeError, UnsupportedFileTypeError
from app.workflows.support.export_import import (
    build_course_export_filename,
    download_course_package,
    export_course,
    get_demo_courses_index_url,
    import_course,
    list_available_courses,
    preview_export,
)
from app.workflows.support.export_import.limits import (
    MAX_IMPORT_PACKAGE_BYTES,
    MAX_IMPORT_PACKAGE_SIZE_MB,
    UPLOAD_COPY_CHUNK_BYTES,
)
from app.workflows.support.courses import get_course_record

router = APIRouter(prefix="/api/v1", tags=["export-import"])

_SUPPORTED_IMPORT_SUFFIXES = {".atmx", ".zip"}


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


@router.post(
    "/courses/{course_id}/export/preview",
    response_model=ApiResponse[ExportPreviewData],
    summary="导出预览",
    responses=build_error_responses([404, 500]),
)
async def export_preview_api(
    course_id: str = Path(...),
    body: ExportOptions = Body(default=ExportOptions()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExportPreviewData]:
    """获取课程导出内容摘要。"""

    normalized = normalize_course_id(course_id)
    course_record = get_course_record(session, normalized, owner_user_id=user.user_id)
    return ok_response(preview_export(session, course_id=course_record.id, options=body))


@router.post(
    "/courses/{course_id}/export",
    summary="导出课程",
    responses=build_error_responses([404, 500]),
)
async def export_course_api(
    course_id: str = Path(...),
    body: ExportOptions = Body(default=ExportOptions()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> FileResponse:
    """将课程全部产物打包为 .atmx 文件下载。"""

    normalized = normalize_course_id(course_id)
    course_record = get_course_record(session, normalized, owner_user_id=user.user_id)
    tmp_path = export_course(session, course_id=course_record.id, options=body)
    filename = build_course_export_filename(course_record)
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
    "/courses/import",
    response_model=ApiResponse[ImportResultData],
    summary="导入课程（上传）",
    responses=build_error_responses([400, 409, 413, 422, 500]),
)
async def import_uploaded_course_api(
    file: UploadFile = File(..., description="上传 .atmx 导出包。"),
    new_course_name: str | None = Form(default=None, description="自定义导入课程名。"),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ImportResultData]:
    """从上传的 .atmx 文件导入课程。"""

    filename = file.filename or "upload.atmx"
    _validate_import_package_filename(filename)
    suffix = Path(filename).suffix or ".atmx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = Path(tmp.name)

    try:
        await _copy_upload_to_temp_file(file, tmp_path)
        result = import_course(
            session,
            file_path=tmp_path,
            options=ImportOptions(new_course_name=new_course_name),
            user_id=user.user_id,
        )
        return ok_response(result)
    finally:
        tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Demo courses catalog
# ---------------------------------------------------------------------------


@router.get(
    "/demo-courses",
    response_model=ApiResponse[list[CoursePackageItem]],
    summary="列出演示课程",
    responses=build_error_responses([500, 502]),
)
async def list_demo_courses_api(response: Response) -> ApiResponse[list[CoursePackageItem]]:
    """列出线上演示课程目录中的课程包。"""

    courses = await run_in_threadpool(list_available_courses)
    _set_no_store_headers(response)
    response.headers["X-Demo-Courses-Count"] = str(len(courses))
    catalog_url = get_demo_courses_index_url()
    if catalog_url:
        response.headers["X-Demo-Courses-Catalog"] = catalog_url
    return ok_response(courses)


@router.post(
    "/demo-courses/{identifier}/import",
    response_model=ApiResponse[ImportResultData],
    summary="从演示课程导入",
    responses=build_error_responses([404, 413, 422, 500, 502]),
)
async def import_demo_course_api(
    identifier: str,
    new_course_name: str | None = Body(default=None, embed=True),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ImportResultData]:
    """从线上演示课程目录下载 `.atmx` 后导入。"""

    tmp_path, _download_name = download_course_package(identifier)
    try:
        result = import_course(
            session,
            file_path=tmp_path,
            options=ImportOptions(new_course_name=new_course_name),
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


def _set_no_store_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"


def _validate_import_package_filename(filename: str) -> None:
    suffix = Path(filename or "upload.atmx").suffix.lower() or ".atmx"
    if suffix not in _SUPPORTED_IMPORT_SUFFIXES:
        raise UnsupportedFileTypeError(suffix)


async def _copy_upload_to_temp_file(file: UploadFile, target_path: Path) -> None:
    bytes_written = 0
    with target_path.open("wb") as fh:
        while True:
            chunk = await file.read(UPLOAD_COPY_CHUNK_BYTES)
            if not chunk:
                break
            bytes_written += len(chunk)
            if bytes_written > MAX_IMPORT_PACKAGE_BYTES:
                raise ImportPackageTooLargeError(MAX_IMPORT_PACKAGE_SIZE_MB)
            fh.write(chunk)
