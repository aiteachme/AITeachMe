"""Normalize the planner's outline sketch into the stable plan payload."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from app.shared.infra.settings import get_settings
from app.workflows.digest.common.runtime_config import get_planner_mode_runtime_config, get_teaching_runtime_config
from app.workflows.digest.common.models import FastTopicHints, SharedInputs, SubjectProfile


class PlannerChapterPlan(BaseModel):
    chapter_index: int
    title: str
    objective: str = ""
    required_elements: list[str] = Field(default_factory=list)
    # Kept for the public confirmed-plan contract; Planner no longer invents queries.
    search_queries: list[str] = Field(default_factory=list)
    writing_instructions: str = ""
    media_hints: dict[str, list[str]] = Field(
        default_factory=lambda: {"images": [], "mermaid": [], "interactive": []}
    )


class BuildPlannerDraft(BaseModel):
    """Stable planner payload consumed by API and DocGen."""

    subject: str
    user_goal: str
    digest_mode: str = "systematic"
    selected_skillpacks: list[str] = Field(default_factory=list)
    chapter_plan: list[PlannerChapterPlan] = Field(default_factory=list)
    # Kept for API/DB compatibility. DocGen derives retrieval queries from chapter content.
    research_queries: list[str] = Field(default_factory=list)
    media_plan: dict[str, Any] = Field(default_factory=dict)
    build_constraints: dict[str, Any] = Field(default_factory=dict)
    plan_summary: str = ""


def _text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _strings(value: Any) -> list[str]:
    items = value if isinstance(value, (list, tuple, set)) else [value]
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _text(item)
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            cleaned.append(text)
    return cleaned


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _chapter_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_mapping(item) for item in value]


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _normalize_digest_mode(value: Any) -> str:
    mode = _text(value or get_teaching_runtime_config().planner.default_digest_mode).lower()
    return "sprint" if mode == "sprint" else "systematic"


def _minimal_shared_inputs(subject: str) -> SharedInputs:
    return SharedInputs(
        fast_hints=FastTopicHints(),
        subject_profile=SubjectProfile(subject_slug=subject, subject_name=""),
    )


def _resolve_subject_display_name(
    subject: str,
    *,
    shared_inputs: SharedInputs | None,
    user_goal: str = "",
) -> str:
    shared = shared_inputs or _minimal_shared_inputs(subject)
    for candidate in [
        shared.subject_profile.subject_name,
        user_goal,
        subject if not _text(subject).lower().startswith("subj_") else "",
    ]:
        text = _text(candidate)
        if text:
            return text
    return "当前主题"


def _merge_chapter(raw: Mapping[str, Any], index: int) -> PlannerChapterPlan:
    title = _text(raw.get("title"))
    key_points = _strings(raw.get("required_elements") or raw.get("key_points"))
    if not title:
        raise ValueError(f"planner chapter #{index} is missing title")
    if not key_points:
        raise ValueError(f"planner chapter `{title}` is missing key_points")
    return PlannerChapterPlan(
        chapter_index=_positive_int(raw.get("chapter_index")) or index,
        title=title,
        objective=_text(raw.get("objective")) or "；".join(key_points),
        required_elements=key_points,
        writing_instructions=_text(raw.get("writing_instructions")) or "围绕本章知识点生成清晰讲解。",
        media_hints={"images": [], "mermaid": [], "interactive": []},
    )


def _media_plan() -> dict[str, Any]:
    settings = get_settings()
    return {
        "enable_mermaid": settings.mermaid_generation_enabled,
        "enable_images": settings.image_generation_enabled,
        "enable_interactive_html": False,
    }


def _build_constraints(*, digest_mode: str, chapter_count: int, shared_inputs: SharedInputs) -> dict[str, Any]:
    config = get_planner_mode_runtime_config(digest_mode)
    target_count = min(config.max_chapters, max(config.min_chapters, chapter_count))
    return {
        "min_chapters": config.min_chapters,
        "max_chapters": config.max_chapters,
        "target_chapter_count": target_count,
        "target_length": config.target_length,
        "include_exercises": True,
        "include_sources": True,
        "math_mode": shared_inputs.subject_profile.has_heavy_formulas,
    }


def normalize_planner_draft(
    draft: BuildPlannerDraft | Mapping[str, Any] | None,
    *,
    subject: str,
    user_goal: str,
    requested_digest_mode: str,
    selected_skillpacks: list[str] | None = None,
    shared_inputs: SharedInputs | None = None,
    latest_plan: BuildPlannerDraft | Mapping[str, Any] | None = None,
) -> BuildPlannerDraft:
    shared = shared_inputs or _minimal_shared_inputs(subject)
    current = _mapping(draft)
    previous = _mapping(latest_plan)
    mode = _normalize_digest_mode(requested_digest_mode or current.get("digest_mode") or previous.get("digest_mode"))
    display_subject = _resolve_subject_display_name(subject, shared_inputs=shared, user_goal=user_goal)

    current_chapters = _chapter_items(current.get("chapter_plan"))
    previous_chapters = _chapter_items(previous.get("chapter_plan"))
    raw_chapters = current_chapters or previous_chapters
    if not raw_chapters:
        raise ValueError("planner plan is missing chapters")

    chapters = [_merge_chapter(raw, index) for index, raw in enumerate(raw_chapters, start=1)]
    plan_summary = _text(current.get("plan_summary") or previous.get("plan_summary"))
    if not plan_summary:
        raise ValueError("planner plan is missing plan_summary")

    skillpacks = (
        selected_skillpacks
        if selected_skillpacks is not None
        else current.get("selected_skillpacks") or previous.get("selected_skillpacks") or []
    )
    return BuildPlannerDraft(
        subject=display_subject,
        user_goal=user_goal,
        digest_mode=mode,
        selected_skillpacks=_strings(skillpacks),
        chapter_plan=chapters,
        research_queries=[],
        media_plan=_media_plan(),
        build_constraints=_build_constraints(digest_mode=mode, chapter_count=len(chapters), shared_inputs=shared),
        plan_summary=plan_summary,
    )


def normalize_planner_payload(
    payload: BuildPlannerDraft | Mapping[str, Any] | None,
    *,
    subject: str,
    user_goal: str,
    requested_digest_mode: str,
    selected_skillpacks: list[str] | None = None,
    shared_inputs: SharedInputs | None = None,
    latest_plan: BuildPlannerDraft | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return normalize_planner_draft(
        payload,
        subject=subject,
        user_goal=user_goal,
        requested_digest_mode=requested_digest_mode,
        selected_skillpacks=selected_skillpacks,
        shared_inputs=shared_inputs,
        latest_plan=latest_plan,
    ).model_dump(mode="json")


__all__ = [
    "BuildPlannerDraft",
    "PlannerChapterPlan",
    "_resolve_subject_display_name",
    "normalize_planner_draft",
    "normalize_planner_payload",
]
