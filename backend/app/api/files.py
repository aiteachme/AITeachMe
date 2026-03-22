"""File APIs."""

from __future__ import annotations

import mimetypes

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Path, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session

from app.api.deps import get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.schemas.common import ApiResponse, ok_response
from app.schemas.files import FileDeleteData, FileDeleteRequest, FilesData, FilesUploadData
from app.services.file_service import (
    delete_files,
    get_file_asset_path,
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
    background_tasks: BackgroundTasks,
    subject: str = Path(...),
    files: list[UploadFile] = File(...),
    session: Session = Depends(get_db),
) -> ApiResponse[FilesUploadData]:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    data = await save_uploaded_files_and_request_parse(session, subject=normalized_subject, files=files)
    if data.accepted_parse_file_ids:
        background_tasks.add_task(
            run_parse_files_background,
            subject=normalized_subject,
            file_ids=data.accepted_parse_file_ids,
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
    session: Session = Depends(get_db),
) -> ApiResponse[FilesData]:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    return ok_response(list_subject_files(session, subject=normalized_subject))


@router.delete(
    "/{file_id}",
    response_model=ApiResponse[FileDeleteData],
    summary="Delete one file",
    responses=build_error_responses([400, 404, 409, 422, 500]),
)
async def delete_file_api(
    subject: str = Path(...),
    file_id: int = Path(...),
    session: Session = Depends(get_db),
) -> ApiResponse[FileDeleteData]:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    return ok_response(delete_files(session, subject=normalized_subject, file_ids=[file_id]))


@router.post(
    "/delete",
    response_model=ApiResponse[FileDeleteData],
    summary="Delete multiple files",
    responses=build_error_responses([400, 404, 409, 422, 500]),
)
async def delete_files_api(
    subject: str = Path(...),
    body: FileDeleteRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[FileDeleteData]:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    file_ids = [body.file_id] if body.file_id is not None else []
    if body.file_ids:
        file_ids.extend(body.file_ids)
    unique_file_ids = list(dict.fromkeys(file_ids))
    return ok_response(delete_files(session, subject=normalized_subject, file_ids=unique_file_ids))


@router.get(
    "/{file_id}/assets/{asset_name}",
    summary="Get one extracted asset",
    responses=build_error_responses([400, 404, 500]),
)
async def get_file_asset_api(
    subject: str = Path(...),
    file_id: int = Path(...),
    asset_name: str = Path(...),
    session: Session = Depends(get_db),
) -> FileResponse:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    asset_path = get_file_asset_path(
        session,
        subject=normalized_subject,
        file_id=file_id,
        asset_name=asset_name,
    )
    return FileResponse(
        path=asset_path,
        filename=asset_path.name,
        media_type=mimetypes.guess_type(asset_path.name)[0] or "application/octet-stream",
    )
