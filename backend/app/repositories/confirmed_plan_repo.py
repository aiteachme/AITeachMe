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
CONFIRMED_PLAN_HISTORY_META_KEY = "confirmed_plan_history"


def _planner_sessions(session: Session, *, course_id: str, user_id: str) -> Iterable[ChatSession]:
    stmt = (
        select(ChatSession)
        .where(
            ChatSession.course_id == course_id,
            ChatSession.user_id == user_id,
            ChatSession.source == PLANNER_CHAT_SOURCE,
        )
        .order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
    )
    return session.exec(stmt).all()


def _meta_from_session(session_item: ChatSession) -> dict[str, Any]:
    raw_meta = session_item.meta_json or {}
    if isinstance(raw_meta, str):
        try:
            raw_meta = json.loads(raw_meta)
        except Exception:
            raw_meta = {}
    return dict(raw_meta or {}) if isinstance(raw_meta, dict) else {}


def _plan_from_payload(payload: Any, session_item: ChatSession) -> ConfirmedBuildPlan | None:
    if not isinstance(payload, dict):
        return None
    payload = dict(payload)
    payload.setdefault("version_no", 1)
    payload.setdefault("planner_session_id", session_item.id)
    payload.setdefault("course_id", session_item.course_id)
    payload.setdefault("user_id", session_item.user_id)
    try:
        return ConfirmedBuildPlan.model_validate(payload)
    except Exception:
        return None


def _plan_from_session(session_item: ChatSession) -> ConfirmedBuildPlan | None:
    meta = _meta_from_session(session_item)
    return _plan_from_payload(meta.get(CONFIRMED_PLAN_META_KEY), session_item)


def _plan_history_from_session(session_item: ChatSession) -> list[ConfirmedBuildPlan]:
    meta = _meta_from_session(session_item)
    plans_by_id: dict[str, ConfirmedBuildPlan] = {}
    current = _plan_from_payload(meta.get(CONFIRMED_PLAN_META_KEY), session_item)
    if current is not None:
        plans_by_id[current.id] = current
    raw_history = meta.get(CONFIRMED_PLAN_HISTORY_META_KEY)
    if isinstance(raw_history, list):
        for payload in raw_history:
            plan = _plan_from_payload(payload, session_item)
            if plan is not None:
                plans_by_id[plan.id] = plan
    return sorted(
        plans_by_id.values(),
        key=lambda item: (int(item.version_no or 0), item.created_at, item.id),
    )


def _plan_payload(record: ConfirmedBuildPlan) -> dict[str, Any]:
    return record.model_dump(mode="json")


def next_confirmed_plan_version_no(session: Session, *, course_id: str, user_id: str) -> int:
    latest = 0
    for session_item in _planner_sessions(session, course_id=course_id, user_id=user_id):
        for plan in _plan_history_from_session(session_item):
            latest = max(latest, int(plan.version_no or 0))
    return latest + 1


def _store_plan_on_session(
    session: Session,
    session_item: ChatSession,
    record: ConfirmedBuildPlan,
    *,
    make_current: bool = True,
) -> ConfirmedBuildPlan:
    meta = _meta_from_session(session_item)
    history_by_id = {plan.id: _plan_payload(plan) for plan in _plan_history_from_session(session_item)}
    history_by_id[record.id] = _plan_payload(record)
    meta[CONFIRMED_PLAN_HISTORY_META_KEY] = sorted(
        history_by_id.values(),
        key=lambda item: (
            int(item.get("version_no") or 0),
            str(item.get("created_at") or ""),
            str(item.get("id") or ""),
        ),
    )
    if make_current:
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
        or session_item.course_id != record.course_id
        or session_item.user_id != record.user_id
        or session_item.source != PLANNER_CHAT_SOURCE
    ):
        raise RuntimeError(f"Planner session `{record.planner_session_id}` was not found.")
    return _store_plan_on_session(session, session_item, record, make_current=True)


def update_confirmed_plan(session: Session, record: ConfirmedBuildPlan) -> ConfirmedBuildPlan:
    if record.planner_session_id:
        session_item = session.get(ChatSession, record.planner_session_id)
        if (
            session_item is not None
            and session_item.course_id == record.course_id
            and session_item.user_id == record.user_id
            and session_item.source == PLANNER_CHAT_SOURCE
        ):
            meta = _meta_from_session(session_item)
            make_current = meta.get("confirmed_plan_id") == record.id
            if make_current or any(plan.id == record.id for plan in _plan_history_from_session(session_item)):
                return _store_plan_on_session(session, session_item, record, make_current=make_current)

    for session_item in _planner_sessions(session, course_id=record.course_id, user_id=record.user_id):
        meta = _meta_from_session(session_item)
        if any(plan.id == record.id for plan in _plan_history_from_session(session_item)):
            return _store_plan_on_session(
                session,
                session_item,
                record,
                make_current=meta.get("confirmed_plan_id") == record.id,
            )
    return record


def get_confirmed_plan(
    session: Session,
    *,
    course_id: str,
    plan_id: str,
    user_id: str,
) -> ConfirmedBuildPlan | None:
    for session_item in _planner_sessions(session, course_id=course_id, user_id=user_id):
        for plan in _plan_history_from_session(session_item):
            if plan.id == plan_id:
                return plan
    return None


def get_confirmed_plan_by_session(
    session: Session,
    *,
    course_id: str,
    planner_session_id: str,
    user_id: str,
) -> ConfirmedBuildPlan | None:
    session_item = session.get(ChatSession, planner_session_id)
    if (
        session_item is None
        or session_item.course_id != course_id
        or session_item.user_id != user_id
        or session_item.source != PLANNER_CHAT_SOURCE
    ):
        return None
    return _plan_from_session(session_item)


__all__ = [
    "CONFIRMED_PLAN_META_KEY",
    "CONFIRMED_PLAN_HISTORY_META_KEY",
    "create_confirmed_plan",
    "get_confirmed_plan",
    "get_confirmed_plan_by_session",
    "next_confirmed_plan_version_no",
    "update_confirmed_plan",
]
