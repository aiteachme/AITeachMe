"""鉴权占位接口。"""

from __future__ import annotations

from fastapi import APIRouter, Body

from app.api.openapi import build_error_responses
from app.schemas.auth import AuthSessionData, LoginRequest, LogoutRequest, RegisterRequest
from app.schemas.common import ApiResponse
from app.services.auth_service import ensure_auth_ready

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=ApiResponse[AuthSessionData],
    summary="注册",
    description="云端鉴权预留接口。",
    responses=build_error_responses([503]),
)
async def register(_: RegisterRequest = Body(...)) -> ApiResponse[AuthSessionData]:
    ensure_auth_ready()
    raise AssertionError("unreachable")


@router.post(
    "/login",
    response_model=ApiResponse[AuthSessionData],
    summary="登录",
    description="云端鉴权预留接口。",
    responses=build_error_responses([503]),
)
async def login(_: LoginRequest = Body(...)) -> ApiResponse[AuthSessionData]:
    ensure_auth_ready()
    raise AssertionError("unreachable")


@router.post(
    "/logout",
    response_model=ApiResponse[AuthSessionData],
    summary="登出",
    description="云端鉴权预留接口。",
    responses=build_error_responses([503]),
)
async def logout(_: LogoutRequest = Body(default=LogoutRequest())) -> ApiResponse[AuthSessionData]:
    ensure_auth_ready()
    raise AssertionError("unreachable")


@router.post(
    "/user",
    response_model=ApiResponse[AuthSessionData],
    summary="当前用户",
    description="云端鉴权预留接口。",
    responses=build_error_responses([503]),
)
async def user(_: LogoutRequest = Body(default=LogoutRequest())) -> ApiResponse[AuthSessionData]:
    ensure_auth_ready()
    raise AssertionError("unreachable")
