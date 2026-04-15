"""Exams API endpoints (offline)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path

from app.api.deps import CurrentUserContext, get_current_user_context
from app.api.openapi import build_error_responses
from app.shared.infra.exceptions import AITeachMeError

router = APIRouter(prefix="/api/v1/subjects/{subject}/exams", tags=["exams"])


def _raise_exams_offline() -> None:
    raise AITeachMeError(
        detail="Exams feature is offline.",
        error_code="EXAMS_OFFLINE",
        status_code=404,
    )


@router.api_route(
    "/",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    summary="Exams feature offline",
    responses=build_error_responses([404]),
)
async def exams_offline_root(
    subject: str = Path(...),
    _: CurrentUserContext = Depends(get_current_user_context),
) -> None:
    del subject
    _raise_exams_offline()


@router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    summary="Exams feature offline",
    responses=build_error_responses([404]),
)
async def exams_offline_path(
    subject: str = Path(...),
    path: str = Path(...),
    _: CurrentUserContext = Depends(get_current_user_context),
) -> None:
    del subject, path
    _raise_exams_offline()
