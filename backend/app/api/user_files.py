"""User-level file library APIs."""

from __future__ import annotations

import mimetypes
from pathlib import Path as FilePath

from fastapi import APIRouter, Body, Depends, File, Form, Path, Query, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlmodel import Session

from app.api.deps import CurrentUserContext, get_current_user_context, get_db
from app.api.openapi import build_error_responses
from app.repositories.files_repo import get_raw_file_by_id_for_user
from app.schemas.common import ApiResponse, ok_response
from app.schemas.files import FileDeleteData, FileDeleteRequest, FilesData, FilesUploadData
from app.shared.infra.storage import get_content_store
from app.workflows.ingest.intake import (
    delete_user_files,
    list_user_files,
    run_parse_files_background,
    save_uploaded_files_and_request_parse,
)

router = APIRouter(prefix="/api/v1/files", tags=["files"])


@router.post(
    "/upload",
    response_model=ApiResponse[FilesUploadData],
    summary="Upload files to the user library and start parsing immediately",
    responses=build_error_responses([400, 413, 422, 500]),
)
async def upload_user_files(
    request: Request,
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
        course_id=None,
        owner_user_id=user.user_id,
        files=files,
        parse_request_metadata=parse_request_metadata,
    )
    if parse_file_ids:
        registry_course = f"files:{user.user_id}"
        request.app.state.background_task_registry.spawn(
            run_parse_files_background(
                user_id=user.user_id,
                file_ids=parse_file_ids,
                background_task_registry=request.app.state.background_task_registry,
            ),
            kind="files.parse",
            course_id=registry_course,
            name=f"files.parse:{registry_course}",
        )
    return ok_response(data)


@router.get(
    "",
    response_model=ApiResponse[FilesData],
    summary="Get user library files with full data",
    responses=build_error_responses([400, 500]),
)
async def list_user_files_api(
    file_ids: list[str] | None = Query(default=None),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[FilesData]:
    unique_file_ids = list(dict.fromkeys(file_ids or [])) or None
    return ok_response(list_user_files(session, owner_user_id=user.user_id, file_ids=unique_file_ids))


@router.post(
    "/delete",
    response_model=ApiResponse[FileDeleteData],
    summary="Delete files from the user library",
    responses=build_error_responses([400, 404, 409, 422, 500]),
)
async def delete_user_files_api(
    body: FileDeleteRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[FileDeleteData]:
    file_ids = [body.file_id] if body.file_id is not None else []
    if body.file_ids:
        file_ids.extend(body.file_ids)
    unique_file_ids = list(dict.fromkeys(file_ids))
    return ok_response(
        await delete_user_files(
            session,
            owner_user_id=user.user_id,
            file_ids=unique_file_ids,
        )
    )


@router.get(
    "/assets/{file_id}/{asset_path:path}",
    summary="Serve a parsed asset for a user-library file",
    responses=build_error_responses([404, 500]),
)
async def serve_user_file_asset(
    file_id: str = Path(...),
    asset_path: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> Response:
    raw_file = get_raw_file_by_id_for_user(session, user_id=user.user_id, file_id=file_id)
    if raw_file is None:
        return Response(status_code=404, content=b"Not found")

    base_prefix = raw_file.asset_dir or get_content_store().user_file_scope(user_id=user.user_id).asset_prefix(
        file_id=raw_file.id,
        filename=raw_file.filename,
    )
    normalized_asset_path = asset_path.lstrip("/\\")
    if not normalized_asset_path or ".." in FilePath(normalized_asset_path.replace("\\", "/")).parts:
        return Response(status_code=404, content=b"Not found")

    storage_key = f"{base_prefix.rstrip('/')}/{normalized_asset_path}"
    media_type = mimetypes.guess_type(asset_path)[0] or "application/octet-stream"

    cs = get_content_store()
    public_url = cs.public_url(storage_key)
    if public_url:
        return RedirectResponse(public_url)

    try:
        data = await cs.read_bytes(storage_key)
        return Response(content=data, media_type=media_type)
    except Exception:
        return Response(status_code=404, content=b"Not found")
