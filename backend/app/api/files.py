"""File APIs."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, File, Form, Path, Request, UploadFile
from sqlmodel import Session

from app.api.deps import CurrentUserContext, get_current_user_context, get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.schemas.common import ApiResponse, ok_response
from app.schemas.files import FileDeleteData, FileDeleteRequest, FilesData, FilesUploadData
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
    # 解析引擎选择（来自前端 settings）。不传则保持当前默认解析链路。
    parser_provider: str | None = Form(default=None),
    # MinerU：个人 Token 与参数（仅当 parser_provider == 'mineru' 时使用）。
    mineru_api_token: str | None = Form(default=None),
    mineru_model_version: str | None = Form(default=None),
    mineru_enable_formula: bool | None = Form(default=None),
    mineru_enable_table: bool | None = Form(default=None),
    mineru_is_ocr: bool | None = Form(default=None),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[FilesUploadData]:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject, owner_user_id=user.user_id)
    parse_request_metadata: dict[str, object] | None = None
    if parser_provider:
        parse_request_metadata = {
            "requested_parser_provider": parser_provider,
        }
        if parser_provider == "mineru":
            parse_request_metadata["mineru"] = {
                "api_token": mineru_api_token,
                "model_version": mineru_model_version,
                "enable_formula": mineru_enable_formula,
                "enable_table": mineru_enable_table,
                "is_ocr": mineru_is_ocr,
            }

    data, parse_file_ids = await save_uploaded_files_and_request_parse(
        session,
        subject=normalized_subject,
        files=files,
        parse_request_metadata=parse_request_metadata,
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
        delete_files(
            session,
            subject=normalized_subject,
            file_uids=unique_file_uids,
        )
    )
