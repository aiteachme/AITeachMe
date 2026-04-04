from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.api.deps import CurrentUserContext, get_current_user_context, get_db
from app.api.openapi import build_error_responses
from app.schemas.common import ApiResponse, PaginatedData, ok_response
from app.schemas.subject import (
    SubjectCreateRequest,
    SubjectDeleteData,
    SubjectDeletePreviewData,
    SubjectDeletePreviewRequest,
    SubjectDeleteRequest,
    SubjectItem,
    SubjectListRequest,
    SubjectUpdateRequest,
)
from app.services.subject_service import (
    create_subject_record,
    delete_subject_record,
    list_subject_records,
    preview_subject_delete,
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
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[SubjectItem]:
    return ok_response(
        create_subject_record(
            session,
            owner_user_id=user.user_id,
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
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[PaginatedData[SubjectItem]]:
    return ok_response(
        list_subject_records(
            session,
            owner_user_id=user.user_id,
            page=body.page,
            size=body.size,
        )
    )


@router.post(
    "/delete/preview",
    response_model=ApiResponse[SubjectDeletePreviewData],
    summary="删除学科预览",
    responses=build_error_responses([400, 404, 500]),
)
async def preview_delete_subject_api(
    body: SubjectDeletePreviewRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[SubjectDeletePreviewData]:
    return ok_response(
        preview_subject_delete(
            session,
            owner_user_id=user.user_id,
            subject_id=body.subject_id,
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
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[SubjectDeleteData]:
    return ok_response(
        delete_subject_record(
            session,
            owner_user_id=user.user_id,
            subject_id=body.subject_id,
            force=body.force,
        )
    )


@router.post(
    "/update",
    response_model=ApiResponse[SubjectItem],
    summary="更新学科",
    responses=build_error_responses([400, 404, 500]),
)
async def update_subject_api(
    body: SubjectUpdateRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[SubjectItem]:
    return ok_response(
        update_subject_record(
            session,
            owner_user_id=user.user_id,
            subject_id=body.subject_id,
            name=body.name,
            description=body.description,
        )
    )
