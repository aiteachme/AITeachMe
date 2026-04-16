"""系统初始化接口。"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from app.api.deps import CurrentUserContext, get_current_user_context
from app.api.openapi import build_error_responses
from app.schemas.common import ApiResponse, ok_response
from app.schemas.system import InitData, InitRequest, SettingsOverviewData
from app.workflows.support.system import build_init_data, build_settings_overview_data

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
    description="返回环境变量与 settings.yaml 合并后的只读设置概览。",
    responses=build_error_responses([500]),
)
async def get_system_settings(
    _: InitRequest = Body(default=InitRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
) -> ApiResponse[SettingsOverviewData]:
    """读取后端设置概览。"""

    del user
    return ok_response(build_settings_overview_data())
