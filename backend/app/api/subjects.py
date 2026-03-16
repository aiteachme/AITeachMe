"""Top-level subject management routes."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.api.deps import get_db
from app.api.openapi import build_error_responses
from app.repositories.models import Subject
from app.schemas.subject import (
    SubjectCreateRequest,
    SubjectDeleteRequest,
    SubjectDeleteResponse,
    SubjectDetailRequest,
    SubjectDetailResponse,
    SubjectItem,
    SubjectListRequest,
    SubjectListResponse,
    SubjectUpdateRequest,
)
from app.services.presenters import require_id
from app.services.subject_service import (
    create_subject_record,
    delete_subject_record,
    get_subject_record,
    list_subject_records,
    normalize_subject_slug,
    update_subject_record,
)

router = APIRouter(prefix="/api/v1/subjects", tags=["subjects"])


def _to_subject_item(subject: Subject) -> SubjectItem:
    return SubjectItem(
        id=require_id(subject.id, "Subject.id"),
        subject=subject.slug,
        name=subject.name,
        description=subject.description,
        created_at=subject.created_at,
        updated_at=subject.updated_at,
    )


@router.post(
    "/add",
    response_model=SubjectDetailResponse,
    summary="Create subject",
    description="Create a new top-level subject container used by files, knowledge, chat, exam, and profile modules.",
    response_description="Newly created subject.",
    responses=build_error_responses([400, 409, 500]),
)
async def create_subject_api(
    body: SubjectCreateRequest = Body(...),
    session: Session = Depends(get_db),
) -> SubjectDetailResponse:
    subject = create_subject_record(
        session,
        slug=body.subject,
        name=body.name,
        description=body.description,
    )
    return SubjectDetailResponse(**_to_subject_item(subject).model_dump())


@router.post(
    "/list",
    response_model=SubjectListResponse,
    summary="List subjects",
    description="Return paginated top-level subjects.",
    response_description="Paginated subject list.",
    responses=build_error_responses([500]),
)
async def list_subjects_api(
    body: SubjectListRequest = Body(default=SubjectListRequest()),
    session: Session = Depends(get_db),
) -> SubjectListResponse:
    items, total = list_subject_records(session, limit=body.limit, offset=body.offset)
    return SubjectListResponse(items=[_to_subject_item(item) for item in items], total=total)


@router.post(
    "/get",
    response_model=SubjectDetailResponse,
    summary="Get subject detail",
    description="Return one subject by its slug.",
    response_description="Subject detail.",
    responses=build_error_responses([400, 404, 500]),
)
async def get_subject_detail_api(
    body: SubjectDetailRequest = Body(...),
    session: Session = Depends(get_db),
) -> SubjectDetailResponse:
    subject = get_subject_record(session, body.subject)
    return SubjectDetailResponse(**_to_subject_item(subject).model_dump())


@router.post(
    "/edit",
    response_model=SubjectDetailResponse,
    summary="Update subject",
    description="Update the subject display name and description.",
    response_description="Updated subject detail.",
    responses=build_error_responses([400, 404, 500]),
)
async def update_subject_api(
    body: SubjectUpdateRequest = Body(...),
    session: Session = Depends(get_db),
) -> SubjectDetailResponse:
    subject = update_subject_record(
        session,
        slug=body.subject,
        name=body.name,
        description=body.description,
    )
    return SubjectDetailResponse(**_to_subject_item(subject).model_dump())


@router.post(
    "/delete",
    response_model=SubjectDeleteResponse,
    summary="Delete subject",
    description="Delete an empty subject. Subjects with related content cannot be deleted.",
    response_description="Deletion result.",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def delete_subject_api(
    body: SubjectDeleteRequest = Body(...),
    session: Session = Depends(get_db),
) -> SubjectDeleteResponse:
    normalized_subject = normalize_subject_slug(body.subject)
    delete_subject_record(session, slug=normalized_subject)
    return SubjectDeleteResponse(deleted=True, subject=normalized_subject)
