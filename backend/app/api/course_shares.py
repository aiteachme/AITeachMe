"""课程分享链接 API。"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Path as PathParam, Request, Response
from sqlmodel import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUserContext, get_current_user_context, get_db, normalize_course_id
from app.api.openapi import build_error_responses
from app.schemas.common import ApiResponse, ok_response
from app.schemas.course_share import (
    CourseShareCreateRequest,
    CourseShareData,
    CourseShareDocumentContent,
    CourseShareImportRequest,
    CourseSharePreviewData,
)
from app.schemas.export_import import ImportResultData
from app.shared.infra.exceptions import AITeachMeError
from app.workflows.support.course_shares import (
    create_course_share,
    import_course_share,
    list_course_shares,
    preview_course_share,
    read_course_share_asset,
    read_course_share_document,
    revoke_course_share,
)
from app.workflows.support.courses import get_course_record
from app.workflows.support.export_import import spawn_imported_embedding_rebuild_background

router = APIRouter(prefix="/api/v1", tags=["course-shares"])

PUBLIC_SHARE_RESPONSE_HEADERS = {
    "Cache-Control": "private, no-store, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow, noarchive",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Content-Security-Policy": "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; sandbox",
}


def _require_registered_user(user: CurrentUserContext) -> None:
    if user.is_authenticated:
        return
    raise AITeachMeError(
        detail="请先登录或注册后再管理课程分享。",
        status_code=401,
        error_code="AUTH_REQUIRED",
    )


def _set_public_share_headers(response: Response) -> None:
    response.headers.update(PUBLIC_SHARE_RESPONSE_HEADERS)


@router.post(
    "/courses/{course_id}/shares",
    response_model=ApiResponse[CourseShareData],
    summary="创建课程分享链接",
    responses=build_error_responses([400, 401, 404, 409, 413, 422, 500]),
)
def create_course_share_api(
    course_id: str = PathParam(...),
    body: CourseShareCreateRequest = Body(default=CourseShareCreateRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[CourseShareData]:
    _require_registered_user(user)
    normalized = normalize_course_id(course_id)
    course = get_course_record(session, normalized, owner_user_id=user.user_id)
    return ok_response(
        create_course_share(
            session,
            course=course,
            owner_user_id=user.user_id,
            export_options=body.export_options,
            expires_in_days=body.expires_in_days,
        )
    )


@router.get(
    "/courses/{course_id}/shares",
    response_model=ApiResponse[list[CourseShareData]],
    summary="列出课程分享链接",
    responses=build_error_responses([400, 401, 404, 500]),
)
def list_course_shares_api(
    course_id: str = PathParam(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[list[CourseShareData]]:
    _require_registered_user(user)
    normalized = normalize_course_id(course_id)
    get_course_record(session, normalized, owner_user_id=user.user_id)
    return ok_response(list_course_shares(session, owner_user_id=user.user_id, course_id=normalized))


@router.delete(
    "/courses/{course_id}/shares/{share_id}",
    response_model=ApiResponse[CourseShareData],
    summary="撤销课程分享链接",
    responses=build_error_responses([400, 401, 404, 500]),
)
def revoke_course_share_api(
    course_id: str = PathParam(...),
    share_id: str = PathParam(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[CourseShareData]:
    _require_registered_user(user)
    normalized = normalize_course_id(course_id)
    get_course_record(session, normalized, owner_user_id=user.user_id)
    return ok_response(
        revoke_course_share(
            session,
            owner_user_id=user.user_id,
            course_id=normalized,
            share_id=share_id,
        )
    )


@router.get(
    "/course-shares/{token}",
    response_model=ApiResponse[CourseSharePreviewData],
    summary="查看课程分享预览",
    responses=build_error_responses([404, 410, 500]),
)
def preview_course_share_api(
    token: str,
    response: Response,
    session: Session = Depends(get_db),
) -> ApiResponse[CourseSharePreviewData]:
    _set_public_share_headers(response)
    return ok_response(preview_course_share(session, token=token))


@router.get(
    "/course-shares/{token}/documents/{doc_id}",
    response_model=ApiResponse[CourseShareDocumentContent],
    summary="查看课程分享知识文档",
    responses=build_error_responses([404, 410, 500]),
)
def read_course_share_document_api(
    token: str,
    doc_id: str,
    response: Response,
    session: Session = Depends(get_db),
) -> ApiResponse[CourseShareDocumentContent]:
    _set_public_share_headers(response)
    return ok_response(read_course_share_document(session, token=token, doc_id=doc_id))


@router.get(
    "/course-shares/{token}/assets/{asset_path:path}",
    summary="读取课程分享快照资产",
    responses=build_error_responses([404, 410, 500]),
)
def read_course_share_asset_api(
    token: str,
    asset_path: str,
    session: Session = Depends(get_db),
) -> Response:
    data, media_type = read_course_share_asset(session, token=token, asset_path=asset_path)
    return Response(
        content=data,
        media_type=media_type,
        headers={
            **PUBLIC_SHARE_RESPONSE_HEADERS,
            "Content-Disposition": "inline",
        },
    )


@router.post(
    "/course-shares/{token}/import",
    response_model=ApiResponse[ImportResultData],
    summary="导入课程分享",
    responses=build_error_responses([401, 404, 410, 413, 422, 500]),
)
async def import_course_share_api(
    request: Request,
    response: Response,
    token: str,
    body: CourseShareImportRequest = Body(default=CourseShareImportRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ImportResultData]:
    _set_public_share_headers(response)
    if not user.is_authenticated:
        raise AITeachMeError(
            detail="请先登录或注册后再保存课程到自己的账号。",
            status_code=401,
            error_code="AUTH_REQUIRED",
        )

    result = await run_in_threadpool(
        import_course_share,
        session,
        token=token,
        user_id=user.user_id,
        new_course_name=body.new_course_name,
    )
    if spawn_imported_embedding_rebuild_background(
        getattr(request.app.state, "background_task_registry", None),
        course_id=result.course_id,
        imported_counts=result.imported_counts,
    ):
        result.warnings.append("课程已导入，检索索引正在后台准备，通常几秒内完成。")
    return ok_response(result)
