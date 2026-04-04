"""File APIs."""

from __future__ import annotations

import mimetypes

from fastapi import APIRouter, Body, Depends, File, Path, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlmodel import Session

from app.api.deps import CurrentUserContext, get_current_user_context, get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.schemas.common import ApiResponse, ok_response
from app.schemas.files import FileDeleteData, FileDeleteRequest, FilesData, FilesUploadData
from app.shared.infra.storage import get_content_store, run_store_sync
from app.services.file_service import (
    delete_files,
    list_subject_files,
    run_parse_files_background,
    save_uploaded_files_and_request_parse,
)
from app.services.subject_service import get_subject_record

router = APIRouter(prefix="/api/v1/subjects/{subject}/files", tags=["files"])


@router.post(
    "/upload",
    response_model=ApiResponse[FilesUploadData],
    summary="Upload files and start parsing immediately",
    responses=build_error_responses([400, 404, 413, 422, 500]),
)
async def upload_files(
    request: Request,
    subject: str = Path(...),
    files: list[UploadFile] = File(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[FilesUploadData]:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject, owner_user_id=user.user_id)
    data, parse_file_ids = await save_uploaded_files_and_request_parse(
        session,
        subject=normalized_subject,
        files=files,
    )
    if parse_file_ids:
        request.app.state.background_task_registry.spawn(
            run_parse_files_background(
                subject=normalized_subject,
                file_ids=parse_file_ids,
            ),
            kind="files.parse",
            subject=normalized_subject,
            name=f"files.parse:{normalized_subject}",
        )
    return ok_response(data)


@router.get(
    "",
    response_model=ApiResponse[FilesData],
    summary="Get all subject files with full data",
    responses=build_error_responses([400, 404, 500]),
)
async def list_files_api(
    subject: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[FilesData]:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject, owner_user_id=user.user_id)
    return ok_response(list_subject_files(session, subject=normalized_subject))


@router.post(
    "/delete",
    response_model=ApiResponse[FileDeleteData],
    summary="Delete files",
    responses=build_error_responses([400, 404, 409, 422, 500]),
)
async def delete_files_api(
    subject: str = Path(...),
    body: FileDeleteRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[FileDeleteData]:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject, owner_user_id=user.user_id)
    file_uids = [body.file_uid] if body.file_uid is not None else []
    if body.file_uids:
        file_uids.extend(body.file_uids)
    unique_file_uids = list(dict.fromkeys(file_uids))
    return ok_response(
        await delete_files(
            session,
            subject=normalized_subject,
            file_uids=unique_file_uids,
        )
    )


@router.get(
    "/assets/{asset_path:path}",
    summary="Serve file asset (images, etc.)",
    responses=build_error_responses([404, 500]),
)
async def serve_file_asset(
    subject: str = Path(...),
    asset_path: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> Response:
    """代理访问文件资产。

    cloud 模式：优先 302 到 CDN，无 CDN 时流式返回。
    local 模式：从本地文件系统返回。
    """
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject, owner_user_id=user.user_id)

    cs = get_content_store()
    storage_key = f"{normalized_subject}/{asset_path}"
    media_type = mimetypes.guess_type(asset_path)[0] or "application/octet-stream"

    # 优先 CDN 公共 URL 302 重定向
    public_url = cs.public_url(storage_key)
    if public_url:
        return RedirectResponse(public_url)

    # 否则通过 ContentStore 读取并流式返回
    try:
        data = await cs.read_bytes(storage_key)
        return Response(content=data, media_type=media_type)
    except Exception:
        return Response(status_code=404, content=b"Not found")

