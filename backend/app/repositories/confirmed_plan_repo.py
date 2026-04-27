"""Persistence helpers for confirmed build plans stored in planner session meta."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from sqlmodel import Session, select

from app.models.build_planner import ConfirmedBuildPlan
from app.models.chat import ChatSession

PLANNER_CHAT_SOURCE = "build_planner"
CONFIRMED_PLAN_META_KEY = "confirmed_plan"


def _planner_sessions(session: Session, *, subject: str, user_id: str) -> Iterable[ChatSession]:
    stmt = (
        select(ChatSession)
        .where(
            ChatSession.subject == subject,
            ChatSession.user_id == user_id,
            ChatSession.source == PLANNER_CHAT_SOURCE,
        )
        .order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
    )
    return session.exec(stmt).all()


def _plan_from_session(session_item: ChatSession) -> ConfirmedBuildPlan | None:
    raw_meta = session_item.meta_json or {}
    if isinstance(raw_meta, str):
        try:
            raw_meta = json.loads(raw_meta)
        except Exception:
            raw_meta = {}
    meta = dict(raw_meta or {}) if isinstance(raw_meta, dict) else {}
    payload = meta.get(CONFIRMED_PLAN_META_KEY)
    if not isinstance(payload, dict):
        return None
    payload = dict(payload)
    payload.setdefault("planner_session_id", session_item.id)
    payload.setdefault("subject", session_item.subject)
    payload.setdefault("user_id", session_item.user_id)
    try:
        return ConfirmedBuildPlan.model_validate(payload)
    except Exception:
        return None


def _plan_payload(record: ConfirmedBuildPlan) -> dict[str, Any]:
    return record.model_dump(mode="json")


def _store_plan_on_session(
    session: Session,
    session_item: ChatSession,
    record: ConfirmedBuildPlan,
) -> ConfirmedBuildPlan:
    raw_meta = session_item.meta_json or {}
    if isinstance(raw_meta, str):
        try:
            raw_meta = json.loads(raw_meta)
        except Exception:
            raw_meta = {}
    meta = dict(raw_meta or {}) if isinstance(raw_meta, dict) else {}
    meta["confirmed_plan_id"] = record.id
    meta[CONFIRMED_PLAN_META_KEY] = _plan_payload(record)
    session_item.meta_json = meta
    session_item.updated_at = record.updated_at
    session_item.last_message_at = record.updated_at
    session.add(session_item)
    session.commit()
    session.refresh(session_item)
    return record


def create_confirmed_plan(session: Session, record: ConfirmedBuildPlan) -> ConfirmedBuildPlan:
    if not record.planner_session_id:
        raise RuntimeError("Confirmed plan requires planner_session_id.")
    session_item = session.get(ChatSession, record.planner_session_id)
    if (
        session_item is None
        or session_item.subject != record.subject
        or session_item.user_id != record.user_id
        or session_item.source != PLANNER_CHAT_SOURCE
    ):
        raise RuntimeError(f"Planner session `{record.planner_session_id}` was not found.")
    return _store_plan_on_session(session, session_item, record)


def update_confirmed_plan(session: Session, record: ConfirmedBuildPlan) -> ConfirmedBuildPlan:
    if record.planner_session_id:
        session_item = session.get(ChatSession, record.planner_session_id)
        if (
            session_item is not None
            and session_item.subject == record.subject
            and session_item.user_id == record.user_id
            and session_item.source == PLANNER_CHAT_SOURCE
        ):
            return _store_plan_on_session(session, session_item, record)

    for session_item in _planner_sessions(session, subject=record.subject, user_id=record.user_id):
        existing = _plan_from_session(session_item)
        if existing is not None and existing.id == record.id:
            return _store_plan_on_session(session, session_item, record)
    return record


def get_confirmed_plan(
    session: Session,
    *,
    subject: str,
    plan_id: str,
    user_id: str,
) -> ConfirmedBuildPlan | None:
    for session_item in _planner_sessions(session, subject=subject, user_id=user_id):
        plan = _plan_from_session(session_item)
        if plan is not None and plan.id == plan_id:
            return plan
    return None


def get_confirmed_plan_by_session(
    session: Session,
    *,
    subject: str,
    planner_session_id: str,
    user_id: str,
) -> ConfirmedBuildPlan | None:
    session_item = session.get(ChatSession, planner_session_id)
    if (
        session_item is None
        or session_item.subject != subject
        or session_item.user_id != user_id
        or session_item.source != PLANNER_CHAT_SOURCE
    ):
        return None
    return _plan_from_session(session_item)


__all__ = [
    "CONFIRMED_PLAN_META_KEY",
    "create_confirmed_plan",
    "get_confirmed_plan",
    "get_confirmed_plan_by_session",
    "update_confirmed_plan",
]
