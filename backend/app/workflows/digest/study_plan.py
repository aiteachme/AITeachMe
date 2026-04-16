"""Study plan derivation and checklist persistence for digest outputs."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime

from pydantic import BaseModel, Field
from sqlmodel import Session

from app.schemas.knowledge import (
    StudyPlanItemResponse,
    StudyPlanPhaseResponse,
    StudyPlanRequest,
    StudyPlanResponse,
)
from app.utils.docgen_store import read_knowledge_build_status
from app.utils.path_helpers import build_knowledge_study_plan_progress_path
from app.utils.time import utcnow

_ANCHOR_RE = re.compile(r"[^\w\u4e00-\u9fff]+")


class StudyPlanProgressStore(BaseModel):
    """Persisted checklist completion state."""

    updated_at: datetime
    completed_items: dict[str, bool] = Field(default_factory=dict)


def _anchorify(text: str) -> str:
    normalized = _ANCHOR_RE.sub("-", text.strip().lower()).strip("-")
    return normalized or "study-item"


def _stable_id(prefix: str, *parts: object) -> str:
    payload = "||".join(str(part) for part in parts if str(part).strip())
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{digest}"


def _read_progress(subject: str) -> StudyPlanProgressStore:
    path = build_knowledge_study_plan_progress_path(subject)
    if not path.exists():
        return StudyPlanProgressStore(updated_at=utcnow())
    try:
        return StudyPlanProgressStore.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return StudyPlanProgressStore(updated_at=utcnow())


def _write_progress(subject: str, progress: StudyPlanProgressStore) -> None:
    path = build_knowledge_study_plan_progress_path(subject)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(progress.model_dump_json(indent=2), encoding="utf-8")


def build_study_plan(session: Session, *, subject: str) -> StudyPlanResponse:
    """Derive a learner-facing study plan from docs+graph outputs."""

    del session
    build_status = read_knowledge_build_status(subject)
    digest_mode = build_status.digest_mode if build_status is not None else None
    mode_reason = build_status.mode_reason if build_status is not None else None
    progress = _read_progress(subject)
    item_id = _stable_id("plan", subject, "graph_docs")
    completed = bool(progress.completed_items.get(item_id, False))

    item = StudyPlanItemResponse(
        id=item_id,
        title=f"{subject} 学习路线",
        summary="基于知识文档与知识图谱完成一次系统复盘与练习。",
        duration_minutes=45 if digest_mode == "sprint" else 60,
        depends_on_ids=[],
        theme_titles=[subject],
        unit_ids=[],
        doc_anchor=_anchorify(subject),
        completed=completed,
    )
    phase = StudyPlanPhaseResponse(
        id=_stable_id("phase", subject, "core"),
        title="阶段 1: 核心掌握",
        summary="围绕知识文档与知识图谱建立稳定理解。",
        duration_minutes=item.duration_minutes,
        completed_items=1 if completed else 0,
        total_items=1,
        items=[item],
    )

    return StudyPlanResponse(
        subject=subject,
        generated_at=utcnow(),
        digest_mode=digest_mode,
        mode_reason=mode_reason,
        total_items=1,
        completed_items=1 if completed else 0,
        phases=[phase],
    )


def handle_study_plan_request(
    session: Session,
    *,
    subject: str,
    payload: StudyPlanRequest | None = None,
) -> StudyPlanResponse:
    """Read or update the study plan through one shared request shape."""

    if payload is not None and payload.item_id and payload.completed is not None:
        progress = _read_progress(subject)
        progress.completed_items[payload.item_id] = payload.completed
        progress.updated_at = utcnow()
        _write_progress(subject, progress)
    return build_study_plan(session, subject=subject)


__all__ = [
    "build_study_plan",
    "handle_study_plan_request",
]
