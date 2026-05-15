"""Small planner-only data contracts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class PlannerBrief(BaseModel):
    """User-visible planning sketch streamed before the final plan."""

    markdown: str = ""


class PlanIntent(BaseModel):
    """Internal planning intent used to steer the final composer."""

    plan_intent: str = ""
    plan_change_mode: str = ""
    target_scope: str = ""
    scope_decision: str = ""
    chapter_count_guidance: str = ""
    requested_chapter_count: int | None = None
    plan_queries: list[str] = Field(default_factory=list)
    content_preferences: list[str] = Field(default_factory=list)
    chapter_split_guidance: str = ""
    adjustment_options: list[str] = Field(default_factory=list)

    @field_validator("plan_queries", "content_preferences", "adjustment_options", mode="before")
    @classmethod
    def _coerce_string_list(cls, value: Any) -> list[str]:
        if value in (None, ""):
            return []
        items = value if isinstance(value, (list, tuple, set)) else [value]
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in items:
            text = " ".join(str(item or "").strip().split())
            key = text.casefold()
            if not text or key in seen:
                continue
            seen.add(key)
            cleaned.append(text)
        return cleaned

    @field_validator(
        "plan_change_mode",
        "target_scope",
        "scope_decision",
        "chapter_count_guidance",
        "chapter_split_guidance",
        mode="before",
    )
    @classmethod
    def _coerce_string(cls, value: Any) -> str:
        return " ".join(str(value or "").strip().split())

    @field_validator("requested_chapter_count", mode="before")
    @classmethod
    def _coerce_requested_chapter_count(cls, value: Any) -> int | None:
        if value in (None, ""):
            return None
        if isinstance(value, bool):
            return None
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None


def build_empty_planner_brief() -> PlannerBrief:
    return PlannerBrief(markdown="")


__all__ = [
    "PlanIntent",
    "PlannerBrief",
    "build_empty_planner_brief",
]
