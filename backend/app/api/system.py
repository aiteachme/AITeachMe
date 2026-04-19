"""系统初始化接口。"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from sqlmodel import Session

from app.api.deps import CurrentUserContext, get_current_user_context, get_db
from app.api.openapi import build_error_responses
from app.schemas.common import ApiResponse, ok_response
from app.schemas.system import InitData, InitRequest, SettingsOverviewData, UpdateUserSettingsRequest
from app.shared.infra.settings import DEFAULT_PROJECT_SETTINGS_FILENAME
from app.workflows.support.system import (
    build_init_data,
    build_settings_overview_data,
    update_user_settings_overview_data,
)

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.post(
    "/init",
    response_model=ApiResponse[InitData],
    summary="初始化系统信息",
    description="返回前端初始化所需的运行时信息。",
    responses=build_error_responses([500]),
)
async def init_system(
    _: InitRequest = Body(default=InitRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
) -> ApiResponse[InitData]:
    """初始化系统元数据。"""

    return ok_response(
        build_init_data(
            user_id=user.user_id,
            email=user.email,
            is_local=user.is_local,
            device_key=user.device_key,
            is_authenticated=user.is_authenticated,
        )
    )


@router.post(
    "/settings",
    response_model=ApiResponse[SettingsOverviewData],
    summary="读取后端设置总览",
    description=f"返回环境变量与 {DEFAULT_PROJECT_SETTINGS_FILENAME} 合并后的只读设置概览。",
    responses=build_error_responses([500]),
)
async def get_system_settings(
    _: InitRequest = Body(default=InitRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[SettingsOverviewData]:
    """读取后端设置概览。"""

    return ok_response(build_settings_overview_data(session=session, user_id=user.user_id))


@router.patch(
    "/settings",
    response_model=ApiResponse[SettingsOverviewData],
    summary="更新当前用户 settings",
    description=f"保存当前用户的非敏感 {DEFAULT_PROJECT_SETTINGS_FILENAME} 同构 settings 覆盖；密钥类环境变量不通过此接口保存。",
    responses=build_error_responses([422, 500]),
)
async def update_system_settings(
    payload: UpdateUserSettingsRequest,
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[SettingsOverviewData]:
    """更新当前用户 settings 覆盖。"""

    return ok_response(
        update_user_settings_overview_data(
            session=session,
            user_id=user.user_id,
            settings_payload=payload.settings,
            reset=payload.reset,
        )
    )
