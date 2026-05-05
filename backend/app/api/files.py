"""File APIs."""

from __future__ import annotations

import mimetypes
from pathlib import Path as FilePath

from fastapi import APIRouter, Body, Depends, File, Form, Path, Request, UploadFile
from fastapi.responses import Response
from sqlmodel import Session

from app.api.deps import CurrentUserContext, get_current_user_context, get_db, normalize_course_id
from app.api.openapi import build_error_responses
from app.schemas.common import ApiResponse, ok_response
from app.schemas.files import FileDeleteData, FileDeleteRequest, FileLinkRequest, FilesData, FilesUploadData
from app.shared.infra.storage import get_content_store
from app.repositories.files_repo import link_raw_files_to_course
from app.workflows.ingest.intake import (
    delete_files,
    get_user_files_or_raise,
    list_course_files,
    ready_file_ids_for_course_indexing,
    run_parse_files_background,
    save_uploaded_files_and_request_parse,
    spawn_index_course_files_background,
)
from app.workflows.support.courses import get_course_record

router = APIRouter(prefix="/api/v1/courses/{course_id}/files", tags=["files"])


def _normalize_safe_asset_path(asset_path: str) -> str | None:
    """Return a storage-relative asset path, or None when traversal is attempted."""

    normalized = str(asset_path or "").lstrip("/\\")
    if not normalized or ".." in FilePath(normalized.replace("\\", "/")).parts:
        return None
    return normalized


@router.post(
    "/upload",
    response_model=ApiResponse[FilesUploadData],
    summary="Upload files and start parsing immediately",
    responses=build_error_responses([400, 404, 413, 422, 500]),
)
async def upload_files(
    request: Request,
    course_id: str = Path(...),
    files: list[UploadFile] = File(...),
    parser_provider: str | None = Form(default=None),
    mineru_api_token: str | None = Form(default=None),
    paddle_ocr_api_token: str | None = Form(default=None),
    mineru_model_version: str | None = Form(default=None),
    mineru_enable_formula: bool | None = Form(default=None),
    mineru_enable_table: bool | None = Form(default=None),
    mineru_is_ocr: bool | None = Form(default=None),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[FilesUploadData]:
    normalized_course_id = normalize_course_id(course_id)
    course_record = get_course_record(session, normalized_course_id, owner_user_id=user.user_id)

    parse_request_metadata: dict[str, object] | None = None
    if any(
        value is not None
        for value in (
            parser_provider,
            mineru_api_token,
            paddle_ocr_api_token,
            mineru_model_version,
            mineru_enable_formula,
            mineru_enable_table,
            mineru_is_ocr,
        )
    ):
        parse_request_metadata = {}
        if parser_provider:
            parse_request_metadata["requested_parser_provider"] = parser_provider
        if any(
            value is not None
            for value in (
                mineru_api_token,
                mineru_model_version,
                mineru_enable_formula,
                mineru_enable_table,
                mineru_is_ocr,
            )
        ):
            parse_request_metadata["mineru"] = {
                "api_token": mineru_api_token,
                "model_version": mineru_model_version,
                "enable_formula": mineru_enable_formula,
                "enable_table": mineru_enable_table,
                "is_ocr": mineru_is_ocr,
            }
        if paddle_ocr_api_token is not None:
            parse_request_metadata["paddle_ocr"] = {
                "api_token": paddle_ocr_api_token,
            }

    data, parse_file_ids = await save_uploaded_files_and_request_parse(
        session,
        course_id=normalized_course_id,
        owner_user_id=user.user_id,
        files=files,
        parse_request_metadata=parse_request_metadata,
        origin_course_name=course_record.name,
    )
    background_task_registry = getattr(request.app.state, "background_task_registry", None)
    if parse_file_ids:
        if background_task_registry is None:
            raise RuntimeError("background_task_registry unavailable")
        background_task_registry.spawn(
            run_parse_files_background(
                user_id=user.user_id,
                course_id=normalized_course_id,
                file_ids=parse_file_ids,
                background_task_registry=background_task_registry,
            ),
            kind="files.parse",
            course_id=normalized_course_id,
            name=f"files.parse:{normalized_course_id}",
            dedupe_key=f"files.parse:{normalized_course_id}:{':'.join(sorted(parse_file_ids))}",
        )
    parse_file_id_set = set(parse_file_ids)
    reused_ready_file_ids = [
        item.id
        for item in data.uploaded_items
        if item.markdown_ready and item.id not in parse_file_id_set
    ]
    spawn_index_course_files_background(
        background_task_registry,
        user_id=user.user_id,
        course_id=normalized_course_id,
        file_ids=reused_ready_file_ids,
        reason="ingest.upload.reused_completed",
    )
    return ok_response(data)


@router.get(
    "",
    response_model=ApiResponse[FilesData],
    summary="Get all course files with full data",
    responses=build_error_responses([400, 404, 500]),
)
async def list_files_api(
    course_id: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[FilesData]:
    normalized_course_id = normalize_course_id(course_id)
    get_course_record(session, normalized_course_id, owner_user_id=user.user_id)
    return ok_response(list_course_files(session, course_id=normalized_course_id))


@router.post(
    "/link",
    response_model=ApiResponse[FilesData],
    summary="Link existing user files to a course",
    responses=build_error_responses([400, 404, 422, 500]),
)
async def link_files_api(
    request: Request,
    course_id: str = Path(...),
    body: FileLinkRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[FilesData]:
    normalized_course_id = normalize_course_id(course_id)
    get_course_record(session, normalized_course_id, owner_user_id=user.user_id)
    raw_files = get_user_files_or_raise(
        session,
        owner_user_id=user.user_id,
        file_ids=list(dict.fromkeys(body.file_ids)),
    )
    link_raw_files_to_course(
        session,
        owner_user_id=user.user_id,
        course_id=normalized_course_id,
        raw_files=raw_files,
    )
    spawn_index_course_files_background(
        getattr(request.app.state, "background_task_registry", None),
        user_id=user.user_id,
        course_id=normalized_course_id,
        file_ids=ready_file_ids_for_course_indexing(raw_files),
        reason="ingest.link.completed",
    )
    return ok_response(list_course_files(session, course_id=normalized_course_id))


@router.post(
    "/delete",
    response_model=ApiResponse[FileDeleteData],
    summary="Delete files",
    responses=build_error_responses([400, 404, 409, 422, 500]),
)
async def delete_files_api(
    course_id: str = Path(...),
    body: FileDeleteRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[FileDeleteData]:
    normalized_course_id = normalize_course_id(course_id)
    get_course_record(session, normalized_course_id, owner_user_id=user.user_id)
    file_ids = [body.file_id] if body.file_id is not None else []
    if body.file_ids:
        file_ids.extend(body.file_ids)
    unique_file_ids = list(dict.fromkeys(file_ids))
    return ok_response(
        await delete_files(
            session,
            course_id=normalized_course_id,
            owner_user_id=user.user_id,
            file_ids=unique_file_ids,
        )
    )


@router.get(
    "/assets/{asset_path:path}",
    summary="Serve file asset (images, etc.)",
    responses=build_error_responses([404, 500]),
)
async def serve_file_asset(
    course_id: str = Path(...),
    asset_path: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> Response:
    """代理访问文件资产。

    通过后端鉴权后代理返回，避免把用户私有 storage key 暴露到公开加速域名。
    """
    normalized_course_id = normalize_course_id(course_id)
    get_course_record(session, normalized_course_id, owner_user_id=user.user_id)

    cs = get_content_store()
    course_scope = cs.course_scope(user_id=user.user_id, course_id=normalized_course_id)
    normalized_asset_path = _normalize_safe_asset_path(asset_path)
    if normalized_asset_path is None:
        return Response(status_code=404, content=b"Not found")
    storage_key = f"{course_scope.namespace}/assets/{normalized_asset_path}"
    media_type = mimetypes.guess_type(asset_path)[0] or "application/octet-stream"

    try:
        data = await cs.read_bytes(storage_key)
        return Response(content=data, media_type=media_type)
    except Exception:
        return Response(status_code=404, content=b"Not found")
