"""System and runtime discovery routes."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from app.api.deps import CurrentUserContext, get_current_user_context
from app.api.openapi import build_error_responses
from app.core.config import get_settings
from app.schemas.system import InitRequest, InitResponse, RuntimeUser

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.post(
    "/init",
    response_model=InitResponse,
    summary="Initialize runtime metadata",
    description="Return runtime mode, auth availability, and feature flags for the frontend shell.",
    response_description="Runtime metadata used before opening a subject page.",
    responses=build_error_responses([500]),
)
async def init_system(
    _: InitRequest = Body(default=InitRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
) -> InitResponse:
    settings = get_settings()
    return InitResponse(
        mode=settings.app_mode,
        auth_enabled=settings.auth_enabled,
        auth_ready=settings.auth_ready,
        current_user=RuntimeUser(user_id=user.user_id, email=user.email, is_local=user.is_local),
        feature_flags={
            "auth": settings.auth_enabled,
            "files": True,
            "knowledge": True,
            "chat": True,
            "exam": True,
            "profile": True,
        },
        version=settings.app_version,
    )
