"""Persistence helpers for build planner entities."""

from __future__ import annotations

from sqlmodel import Session, select

from app.models.build_planner import BuildPlannerSession, BuildPlannerTurn, ConfirmedBuildPlan


def create_planner_session(session: Session, record: BuildPlannerSession) -> BuildPlannerSession:
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def update_planner_session(session: Session, record: BuildPlannerSession) -> BuildPlannerSession:
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def get_planner_session(
    session: Session,
    *,
    subject: str,
    session_id: str,
    user_id: str,
) -> BuildPlannerSession | None:
    stmt = select(BuildPlannerSession).where(
        BuildPlannerSession.subject == subject,
        BuildPlannerSession.id == session_id,
        BuildPlannerSession.user_id == user_id,
    )
    return session.exec(stmt).first()


def create_planner_turn(session: Session, record: BuildPlannerTurn) -> BuildPlannerTurn:
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def list_planner_turns(session: Session, *, session_id: str) -> list[BuildPlannerTurn]:
    stmt = (
        select(BuildPlannerTurn)
        .where(BuildPlannerTurn.session_id == session_id)
        .order_by(BuildPlannerTurn.created_at.asc(), BuildPlannerTurn.id.asc())
    )
    return list(session.exec(stmt).all())


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
    "create_planner_session",
    "create_planner_turn",
    "get_confirmed_plan",
    "get_confirmed_plan_by_session",
    "get_planner_session",
    "list_planner_turns",
    "update_confirmed_plan",
    "update_planner_session",
]
