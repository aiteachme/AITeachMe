"""Subject-scoped raw file upload, parse, and preview routes."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, File, Path, UploadFile
from sqlmodel import Session

from app.api.deps import get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.repositories.ingest_repo import list_raw_files_by_subject
from app.schemas.upload import (
    FileGetRequest,
    FileGetResponse,
    FileListRequest,
    FileListResponse,
    FilesParseRequest,
    FilesParseResponse,
    FilesUploadResponse,
    FileStatusRequest,
    FileStatusResponse,
)
from app.services.file_service import (
    get_subject_file_or_raise,
    list_asset_payload,
    parse_files,
    read_markdown_content,
    save_uploaded_files,
)
from app.services.presenters import require_id, to_file_get_response, to_file_list_response, to_file_status_response
from app.services.subject_service import get_subject_record

router = APIRouter(prefix="/api/v1/subjects/{subject}/files", tags=["files"])


@router.post(
    "/upload",
    response_model=FilesUploadResponse,
    summary="Upload raw files",
    description="Accept one or more study files and persist them under the selected subject.",
    response_description="Accepted raw file identifiers.",
    responses=build_error_responses([400, 404, 413, 422, 500]),
)
async def upload_files(
    subject: str = Path(..., description="Top-level subject slug.", examples=["math"]),
    files: list[UploadFile] = File(..., description="One or more study files."),
    session: Session = Depends(get_db),
) -> FilesUploadResponse:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)

    saved = await save_uploaded_files(session, subject=normalized_subject, files=files)
    return FilesUploadResponse(
        subject=normalized_subject,
        file_ids=[require_id(item.id, "RawFile.id") for item in saved],
        filenames=[item.filename for item in saved],
    )


@router.post(
    "/parse",
    response_model=FilesParseResponse,
    summary="Parse uploaded files",
    description="Parse one or more uploaded raw files into markdown and assets.",
    response_description="Parse results for this request.",
    responses=build_error_responses([400, 404, 422, 500]),
)
async def parse_uploaded_files(
    subject: str = Path(..., description="Top-level subject slug.", examples=["math"]),
    body: FilesParseRequest = Body(...),
    session: Session = Depends(get_db),
) -> FilesParseResponse:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)

    parsed, failed = await parse_files(session, subject=normalized_subject, file_ids=body.file_ids)
    return FilesParseResponse(
        parsed_file_ids=[require_id(item.id, "RawFile.id") for item in parsed],
        failed=failed,
    )


@router.post(
    "/status",
    response_model=FileStatusResponse,
    summary="Get one file status",
    description="Return status metadata for one uploaded raw file without returning the full markdown text.",
    response_description="Single file status.",
    responses=build_error_responses([400, 404, 500]),
)
async def get_file_status(
    subject: str = Path(..., description="Top-level subject slug.", examples=["math"]),
    body: FileStatusRequest = Body(...),
    session: Session = Depends(get_db),
) -> FileStatusResponse:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    raw_file = get_subject_file_or_raise(session, subject=normalized_subject, file_id=body.file_id)
    return to_file_status_response(raw_file)


@router.post(
    "/list",
    response_model=FileListResponse,
    summary="List uploaded files",
    description="Return a paginated raw file list for one subject.",
    response_description="Paginated file list.",
    responses=build_error_responses([400, 404, 500]),
)
async def list_files(
    subject: str = Path(..., description="Top-level subject slug.", examples=["math"]),
    body: FileListRequest = Body(default=FileListRequest()),
    session: Session = Depends(get_db),
) -> FileListResponse:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)

    items, total = list_raw_files_by_subject(
        session,
        normalized_subject,
        limit=body.limit,
        offset=body.offset,
        parse_status=body.parse_status,
    )
    return to_file_list_response(items, total)


@router.post(
    "/get",
    response_model=FileGetResponse,
    summary="Get parsed file result",
    description="Return the parsed markdown and extracted assets for one raw file.",
    response_description="Parsed file content.",
    responses=build_error_responses([400, 404, 500]),
)
async def get_file(
    subject: str = Path(..., description="Top-level subject slug.", examples=["math"]),
    body: FileGetRequest = Body(...),
    session: Session = Depends(get_db),
) -> FileGetResponse:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    raw_file = get_subject_file_or_raise(session, subject=normalized_subject, file_id=body.file_id)
    return to_file_get_response(
        raw_file,
        markdown_content=read_markdown_content(raw_file),
        assets=list_asset_payload(raw_file),
    )
