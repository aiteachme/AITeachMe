"""Persistence helpers for confirmed build plans."""

from __future__ import annotations

from sqlmodel import Session, select

from app.models.build_planner import ConfirmedBuildPlan


def create_confirmed_plan(session: Session, record: ConfirmedBuildPlan) -> ConfirmedBuildPlan:
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def update_confirmed_plan(session: Session, record: ConfirmedBuildPlan) -> ConfirmedBuildPlan:
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def get_confirmed_plan(
    session: Session,
    *,
    subject: str,
    plan_id: str,
    user_id: str,
) -> ConfirmedBuildPlan | None:
    stmt = select(ConfirmedBuildPlan).where(
        ConfirmedBuildPlan.subject == subject,
        ConfirmedBuildPlan.id == plan_id,
        ConfirmedBuildPlan.user_id == user_id,
    )
    return session.exec(stmt).first()


def get_confirmed_plan_by_session(
    session: Session,
    *,
    subject: str,
    planner_session_id: str,
    user_id: str,
) -> ConfirmedBuildPlan | None:
    stmt = select(ConfirmedBuildPlan).where(
        ConfirmedBuildPlan.subject == subject,
        ConfirmedBuildPlan.planner_session_id == planner_session_id,
        ConfirmedBuildPlan.user_id == user_id,
    )
    return session.exec(stmt).first()


__all__ = [
    "create_confirmed_plan",
    "get_confirmed_plan",
    "get_confirmed_plan_by_session",
    "update_confirmed_plan",
]
