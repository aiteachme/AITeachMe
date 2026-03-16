"""Auth scaffolding routes kept intentionally minimal for future cloud mode work."""

from __future__ import annotations

from fastapi import APIRouter, Body

from app.api.openapi import build_error_responses
from app.core.config import get_settings
from app.core.exceptions import AuthDisabledError, AuthNotReadyError
from app.schemas.auth import AuthSessionResponse, LoginRequest, LogoutRequest, RegisterRequest

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _ensure_auth_ready() -> None:
    settings = get_settings()
    if not settings.auth_enabled or settings.is_local_mode:
        raise AuthDisabledError()
    raise AuthNotReadyError()


@router.post(
    "/register",
    response_model=AuthSessionResponse,
    summary="Register with email",
    description="Cloud auth placeholder for future email registration.",
    response_description="Reserved auth session response shape.",
    responses=build_error_responses([503]),
)
async def register(_: RegisterRequest = Body(...)) -> AuthSessionResponse:
    _ensure_auth_ready()
    raise AssertionError("unreachable")


@router.post(
    "/login",
    response_model=AuthSessionResponse,
    summary="Login with email",
    description="Cloud auth placeholder for future email login.",
    response_description="Reserved auth session response shape.",
    responses=build_error_responses([503]),
)
async def login(_: LoginRequest = Body(...)) -> AuthSessionResponse:
    _ensure_auth_ready()
    raise AssertionError("unreachable")


@router.post(
    "/logout",
    response_model=AuthSessionResponse,
    summary="Logout",
    description="Cloud auth placeholder for future logout.",
    response_description="Reserved auth session response shape.",
    responses=build_error_responses([503]),
)
async def logout(_: LogoutRequest = Body(default=LogoutRequest())) -> AuthSessionResponse:
    _ensure_auth_ready()
    raise AssertionError("unreachable")


@router.post(
    "/user",
    response_model=AuthSessionResponse,
    summary="Get current auth session",
    description="Cloud auth placeholder for future session lookup.",
    response_description="Reserved auth session response shape.",
    responses=build_error_responses([503]),
)
async def user(_: LogoutRequest = Body(default=LogoutRequest())) -> AuthSessionResponse:
    _ensure_auth_ready()
    raise AssertionError("unreachable")
