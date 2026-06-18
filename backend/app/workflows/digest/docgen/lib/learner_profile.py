"""Load persisted learner profile context for DocGen."""

from __future__ import annotations

from typing import Any

from app.models import Course
from app.shared.infra.database import managed_session
from app.workflows.profile.common.lib.course_profile import load_course_profile_summary
from app.workflows.profile.common.lib.profile_text import render_course_profile_text, render_user_profile_text
from app.workflows.profile.common.lib.user_profile import load_user_profile_summary


def _profile_text(payload: dict[str, Any], *, kind: str, course_name: str = "") -> str:
    existing = str(payload.get("profile_text") or "").strip()
    if existing:
        return existing
    if kind == "course":
        return render_course_profile_text(payload, course_name=course_name)
    return render_user_profile_text(payload)


def load_docgen_learner_profile_context(
    *,
    course_id: str,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Return persisted user/course profile context, or an empty context."""

    with managed_session() as session:
        course = session.get(Course, course_id)
        resolved_user_id = (user_id or "").strip() or (course.user_id if course is not None else "")
        user_profile = (
            load_user_profile_summary(session, user_id=resolved_user_id)
            if resolved_user_id
            else None
        )
        course_profile = load_course_profile_summary(session, course_id=course_id)
        course_name = course.name if course is not None else ""

    user_payload = user_profile.model_dump(mode="json") if user_profile is not None else {}
    course_payload = course_profile.model_dump(mode="json") if course_profile is not None else {}
    user_text = _profile_text(user_payload, kind="user") if user_payload else ""
    course_text = (
        _profile_text(course_payload, kind="course", course_name=course_name)
        if course_payload
        else ""
    )
    learner_text = "\n".join(item for item in [user_text, course_text] if item).strip()
    return {
        "schema_version": 1,
        "course_id": course_id,
        "user_id": resolved_user_id,
        "has_profile": bool(learner_text),
        "profile_text": learner_text,
        "user_profile_text": user_text,
        "course_profile_text": course_text,
        "user_profile": user_payload,
        "course_profile": course_payload,
    }


__all__ = ["load_docgen_learner_profile_context"]
