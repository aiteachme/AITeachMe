from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Request
from sqlmodel import Session

from app.api.deps import CurrentUserContext, get_current_user_context, get_db
from app.api.openapi import build_error_responses
from app.schemas.common import ApiResponse, PaginatedData, ok_response
from app.schemas.course import (
    CourseDeleteData,
    CourseDeletePreviewData,
    CourseDeletePreviewRequest,
    CourseDeleteRequest,
    CourseItem,
    CourseListRequest,
    CourseUpdateRequest,
)
from app.shared.infra.analytics.posthog import capture_product_event_later
from app.workflows.support.courses import (
    create_course_record,
    delete_course_record,
    infer_course_icon_key,
    list_course_records,
    preview_course_delete,
    schedule_course_icon_refinement,
    update_course_record,
)

router = APIRouter(prefix="/api/v1/courses", tags=["courses"])


def _create_course_draft(session: Session, user: CurrentUserContext) -> CourseItem:
    item = create_course_record(
        session,
        owner_user_id=user.user_id,
        name="",
        description="",
        user_intent="",
    )
    capture_product_event_later(
        "course_created",
        user_id=user.user_id,
        course_id=item.course_id,
        device_key=user.device_key,
        email=user.email,
        is_authenticated=user.is_authenticated,
        insert_id_parts=[item.course_id, "draft"],
        properties={
            "course_creation_mode": "draft",
            "has_name": bool((item.name or "").strip()),
            "has_description": bool((item.description or "").strip()),
        },
    )
    return item


@router.post(
    "/draft",
    response_model=ApiResponse[CourseItem],
    summary="创建课程草稿",
    responses=build_error_responses([400, 409, 500]),
)
async def create_course_draft_api(
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[CourseItem]:
    return ok_response(_create_course_draft(session, user))


@router.post(
    "/add",
    response_model=ApiResponse[CourseItem],
    include_in_schema=False,
    responses=build_error_responses([400, 409, 500]),
)
async def create_course_draft_legacy_api(
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[CourseItem]:
    return ok_response(_create_course_draft(session, user))


@router.post(
    "/list",
    response_model=ApiResponse[PaginatedData[CourseItem]],
    summary="课程列表",
    responses=build_error_responses([500]),
)
async def list_courses_api(
    body: CourseListRequest = Body(default=CourseListRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[PaginatedData[CourseItem]]:
    return ok_response(
        list_course_records(
            session,
            owner_user_id=user.user_id,
            page=body.page,
            size=body.size,
        )
    )


@router.post(
    "/delete/preview",
    response_model=ApiResponse[CourseDeletePreviewData],
    summary="删除课程预览",
    responses=build_error_responses([400, 404, 500]),
)
async def preview_delete_course_api(
    body: CourseDeletePreviewRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[CourseDeletePreviewData]:
    return ok_response(
        preview_course_delete(
            session,
            owner_user_id=user.user_id,
            course_id=body.course_id,
        )
    )


@router.post(
    "/delete",
    response_model=ApiResponse[CourseDeleteData],
    summary="删除课程",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def delete_course_api(
    request: Request,
    body: CourseDeleteRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[CourseDeleteData]:
    return ok_response(
        await delete_course_record(
            session,
            owner_user_id=user.user_id,
            course_id=body.course_id,
            force=body.force,
            known_detail_counts=body.known_detail_counts,
            background_task_registry=getattr(request.app.state, "background_task_registry", None),
        )
    )


@router.post(
    "/update",
    response_model=ApiResponse[CourseItem],
    summary="更新课程",
    responses=build_error_responses([400, 404, 500]),
)
async def update_course_api(
    request: Request,
    body: CourseUpdateRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[CourseItem]:
    icon_key = infer_course_icon_key(body.name) if body.name is not None else None
    item = update_course_record(
        session,
        owner_user_id=user.user_id,
        course_id=body.course_id,
        name=body.name,
        description=body.description,
        user_intent=body.user_intent,
        icon_key=icon_key,
    )
    if body.name is not None:
        schedule_course_icon_refinement(
            _get_background_task_registry(request),
            course_id=item.course_id,
            owner_user_id=user.user_id,
            course_name=item.name,
        )
    return ok_response(item)


def _get_background_task_registry(request: Request):
    return getattr(request.app.state, "background_task_registry", None)
