from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.api.deps import get_db
from app.api.openapi import build_error_responses
from app.schemas.common import ApiResponse, PaginatedData, ok_response
from app.schemas.subject import (
    SubjectCreateRequest,
    SubjectDeleteData,
    SubjectDeleteRequest,
    SubjectDetailRequest,
    SubjectItem,
    SubjectListRequest,
    SubjectUpdateRequest,
)
from app.services.subject_service import (
    create_subject_record,
    delete_subject_record,
    get_subject_detail,
    list_subject_records,
    update_subject_record,
)

router = APIRouter(prefix="/api/v1/subjects", tags=["subjects"])


@router.post(
    "/add",
    response_model=ApiResponse[SubjectItem],
    summary="创建学科",
    responses=build_error_responses([400, 409, 500]),
)
async def create_subject_api(
    body: SubjectCreateRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[SubjectItem]:
    return ok_response(
        create_subject_record(
            session,
            name=body.name,
            description=body.description,
        )
    )


@router.post(
    "/list",
    response_model=ApiResponse[PaginatedData[SubjectItem]],
    summary="学科列表",
    responses=build_error_responses([500]),
)
async def list_subjects_api(
    body: SubjectListRequest = Body(default=SubjectListRequest()),
    session: Session = Depends(get_db),
) -> ApiResponse[PaginatedData[SubjectItem]]:
    return ok_response(list_subject_records(session, page=body.page, size=body.size))


@router.post(
    "/get",
    response_model=ApiResponse[SubjectItem],
    summary="学科详情",
    responses=build_error_responses([400, 404, 500]),
)
async def get_subject_detail_api(
    body: SubjectDetailRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[SubjectItem]:
    return ok_response(get_subject_detail(session, body.subject_id))


@router.post(
    "/edit",
    response_model=ApiResponse[SubjectItem],
    summary="更新学科",
    responses=build_error_responses([400, 404, 500]),
)
async def update_subject_api(
    body: SubjectUpdateRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[SubjectItem]:
    return ok_response(
        update_subject_record(
            session,
            subject_id=body.subject_id,
            name=body.name,
            description=body.description,
        )
    )


@router.post(
    "/delete",
    response_model=ApiResponse[SubjectDeleteData],
    summary="删除学科",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def delete_subject_api(
    body: SubjectDeleteRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[SubjectDeleteData]:
    return ok_response(delete_subject_record(session, subject_id=body.subject_id))
