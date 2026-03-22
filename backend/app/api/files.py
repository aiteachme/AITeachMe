"""文件接口。"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Path, UploadFile
from sqlmodel import Session

from app.api.deps import get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.schemas.common import ApiResponse, PaginatedData, ok_response
from app.schemas.files import (
    FileDeleteData,
    FileDeleteRequest,
    FileGetData,
    FileGetRequest,
    FileItem,
    FileListRequest,
    FileRetryRequest,
    FilesParseData,
    FilesParseRequest,
    FilesUploadData,
)
from app.services.file_service import (
    delete_files,
    get_file_result,
    list_files,
    request_files_parse,
    retry_file_parse,
    run_parse_files_background,
    save_uploaded_files_and_request_parse,
)
from app.services.subject_service import get_subject_record

router = APIRouter(prefix="/api/v1/subjects/{subject}/files", tags=["files"])


@router.post(
    "/upload",
    response_model=ApiResponse[FilesUploadData],
    summary="上传文件",
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


@router.post(
    "/parse",
    response_model=ApiResponse[FilesParseData],
    summary="解析文件",
    responses=build_error_responses([400, 404, 422, 500]),
)
async def parse_uploaded_files(
    background_tasks: BackgroundTasks,
    subject: str = Path(...),
    body: FilesParseRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[FilesParseData]:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    data = request_files_parse(session, subject=normalized_subject, file_ids=body.file_ids)
    background_tasks.add_task(
        run_parse_files_background,
        subject=normalized_subject,
        file_ids=data.accepted_file_ids,
    )
    return ok_response(data)


@router.post(
    "/retry",
    response_model=ApiResponse[FilesParseData],
    summary="重试解析",
    responses=build_error_responses([400, 404, 422, 500]),
)
async def retry_uploaded_file(
    background_tasks: BackgroundTasks,
    subject: str = Path(...),
    body: FileRetryRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[FilesParseData]:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    data = retry_file_parse(session, subject=normalized_subject, file_id=body.file_id)
    background_tasks.add_task(
        run_parse_files_background,
        subject=normalized_subject,
        file_ids=data.accepted_file_ids,
    )
    return ok_response(data)


@router.post(
    "/list",
    response_model=ApiResponse[PaginatedData[FileItem]],
    summary="文件列表",
    responses=build_error_responses([400, 404, 500]),
)
async def list_files_api(
    subject: str = Path(...),
    body: FileListRequest = Body(default=FileListRequest()),
    session: Session = Depends(get_db),
) -> ApiResponse[PaginatedData[FileItem]]:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    return ok_response(
        list_files(
            session,
            subject=normalized_subject,
            page=body.page,
            size=body.size,
            status=body.status,
        )
    )


@router.post(
    "/get",
    response_model=ApiResponse[FileGetData],
    summary="文件解析结果",
    responses=build_error_responses([400, 404, 500]),
)
async def get_file_api(
    subject: str = Path(...),
    body: FileGetRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[FileGetData]:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    return ok_response(get_file_result(session, subject=normalized_subject, file_id=body.file_id))


@router.post(
    "/delete",
    response_model=ApiResponse[FileDeleteData],
    summary="删除文件",
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
