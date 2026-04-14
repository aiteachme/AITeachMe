"""Docs domain adapter for build-planner services.

This module keeps a stable new namespace while delegating to the legacy
implementation. Wrapper functions synchronize selected patchable symbols so
tests and callsites can monkeypatch this module directly.
"""

from __future__ import annotations

from sqlmodel import Session

from app.models.build_planner import ConfirmedBuildPlan
from app.models.subject import Subject
from app.schemas.knowledge import (
    BuildPlannerConfirmResponse,
    BuildPlannerCreateRequest,
    BuildPlannerMessageRequest,
    BuildPlannerSessionResponse,
)
from app.workflows.digest.planner.runtime import run_build_planner_workflow
import app.services.knowledge.build_planner_service as _legacy


def _sync_patchable_symbols() -> None:
    _legacy.run_build_planner_workflow = run_build_planner_workflow


async def create_build_planner_session_service(
    session: Session,
    *,
    subject: Subject,
    user_id: str,
    payload: BuildPlannerCreateRequest,
    progress_callback=None,
    token_callback=None,
) -> BuildPlannerSessionResponse:
    _sync_patchable_symbols()
    return await _legacy.create_build_planner_session_service(
        session,
        subject=subject,
        user_id=user_id,
        payload=payload,
        progress_callback=progress_callback,
        token_callback=token_callback,
    )


async def append_build_planner_message_service(
    session: Session,
    *,
    subject: Subject,
    user_id: str,
    session_id: str,
    payload: BuildPlannerMessageRequest,
    progress_callback=None,
    token_callback=None,
) -> BuildPlannerSessionResponse:
    _sync_patchable_symbols()
    return await _legacy.append_build_planner_message_service(
        session,
        subject=subject,
        user_id=user_id,
        session_id=session_id,
        payload=payload,
        progress_callback=progress_callback,
        token_callback=token_callback,
    )


def confirm_build_planner_session_service(
    session: Session,
    *,
    subject: Subject,
    user_id: str,
    session_id: str,
) -> BuildPlannerConfirmResponse:
    return _legacy.confirm_build_planner_session_service(
        session,
        subject=subject,
        user_id=user_id,
        session_id=session_id,
    )


def get_confirmed_build_plan_service(
    session: Session,
    *,
    subject: str,
    user_id: str,
    plan_id: str,
) -> ConfirmedBuildPlan:
    return _legacy.get_confirmed_build_plan_service(
        session,
        subject=subject,
        user_id=user_id,
        plan_id=plan_id,
    )


def mark_confirmed_build_plan_status(
    session: Session,
    *,
    subject: str,
    user_id: str,
    plan_id: str,
    status: str,
) -> ConfirmedBuildPlan:
    return _legacy.mark_confirmed_build_plan_status(
        session,
        subject=subject,
        user_id=user_id,
        plan_id=plan_id,
        status=status,
    )


def get_latest_planner_session_service(
    session: Session,
    *,
    subject: Subject,
    user_id: str,
) -> BuildPlannerSessionResponse | None:
    return _legacy.get_latest_planner_session_service(
        session,
        subject=subject,
        user_id=user_id,
    )


__all__ = [
    "append_build_planner_message_service",
    "confirm_build_planner_session_service",
    "create_build_planner_session_service",
    "get_confirmed_build_plan_service",
    "get_latest_planner_session_service",
    "mark_confirmed_build_plan_status",
    "run_build_planner_workflow",
]

