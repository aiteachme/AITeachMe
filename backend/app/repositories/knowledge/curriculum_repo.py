"""Legacy curriculum repository helpers used by examine/profile workflows."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlmodel import Session, select

from app.models import Curriculum, TeachingUnit


@dataclass(frozen=True)
class UnitMembership:
    """One knowledge-node membership inside a teaching unit."""

    knowledge_node_id: int
    role: str = "primary"
    score: float = 1.0


def get_current_curriculum_snapshot(session: Session, subject: str) -> Curriculum | None:
    """Return the current published curriculum snapshot for a subject."""

    return session.exec(
        select(Curriculum)
        .where(
            Curriculum.subject == subject,
            Curriculum.status == "published",
            Curriculum.is_current == True,  # noqa: E712
        )
        .order_by(Curriculum.version_no.desc(), Curriculum.id.desc())
    ).first()


def get_teaching_unit_by_id(session: Session, unit_id: int) -> TeachingUnit | None:
    """Return one teaching unit by id."""

    return session.get(TeachingUnit, unit_id)


def list_memberships_by_unit(session: Session, unit_id: int) -> list[UnitMembership]:
    """Return parsed knowledge-node memberships for a teaching unit."""

    unit = session.get(TeachingUnit, unit_id)
    if unit is None:
        return []
    try:
        raw_items = json.loads(unit.member_node_refs_json or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(raw_items, list):
        return []

    memberships: list[UnitMembership] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        raw_node_id = item.get("knowledge_node_id")
        if not isinstance(raw_node_id, int):
            continue
        memberships.append(
            UnitMembership(
                knowledge_node_id=raw_node_id,
                role=str(item.get("role") or "primary"),
                score=float(item.get("score") or item.get("coverage_weight") or 1.0),
            )
        )
    return memberships


__all__ = [
    "UnitMembership",
    "get_current_curriculum_snapshot",
    "get_teaching_unit_by_id",
    "list_memberships_by_unit",
]
