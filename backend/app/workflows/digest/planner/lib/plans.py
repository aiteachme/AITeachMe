"""Normalize the planner's outline sketch into the stable plan payload."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from app.workflows.digest.common.runtime_config import get_planner_mode_runtime_config, get_teaching_runtime_config
from app.workflows.digest.common.models import FastTopicHints, SharedInputs, SubjectProfile


class PlannerChapterPlan(BaseModel):
    chapter_index: int
    title: str
    objective: str = ""
    required_elements: list[str] = Field(default_factory=list)
    writing_instructions: str = ""


class BuildPlannerDraft(BaseModel):
    """Stable planner payload consumed by API and DocGen."""

    subject: str
    user_prompt: str
    digest_mode: str = "systematic"
    chapter_plan: list[PlannerChapterPlan] = Field(default_factory=list)
    build_constraints: dict[str, Any] = Field(default_factory=dict)
    plan_summary: str = ""
    plan_steps: list[str] = Field(default_factory=list)


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


def _topic_strings(shared_inputs: SharedInputs, *, user_prompt: str, subject: str) -> list[str]:
    values: list[Any] = [
        *shared_inputs.fast_hints.chapter_candidates,
        *[name for name, _count in shared_inputs.fast_hints.high_freq_terms],
        *shared_inputs.subject_profile.key_topics,
        shared_inputs.subject_profile.sub_discipline,
        shared_inputs.subject_profile.discipline,
        user_prompt,
        subject,
    ]
    return _strings(values)


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
    user_prompt: str = "",
) -> str:
    shared = shared_inputs or _minimal_shared_inputs(subject)
    for candidate in [
        shared.subject_profile.subject_name,
        user_prompt,
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
    )


def _build_supplement_chapter(
    *,
    index: int,
    topic: str,
    digest_mode: str,
    user_prompt: str,
) -> PlannerChapterPlan:
    title = _text(topic) or f"补充章节 {index}"
    normalized_mode = _normalize_digest_mode(digest_mode)
    if normalized_mode == "sprint":
        required = _strings([f"{title} 的高频考点", f"{title} 的典型题型", f"{title} 的易错点"])
        objective = f"把《{title}》整理成考前可快速复盘的考点、题型和易错清单。"
        writing = "按速成课写法组织：先给抓手，再讲题型和易错点。"
    else:
        required = _strings([f"{title} 的核心概念", f"{title} 的关键结构", f"{title} 的例子与迁移"])
        objective = f"系统讲清《{title}》的概念边界、结构关系和典型应用。"
        writing = "按系统课写法组织：先讲定义和结构，再展开推理、例子与迁移。"
    if user_prompt:
        required = _strings([*required, user_prompt])
    return PlannerChapterPlan(
        chapter_index=index,
        title=title,
        objective=objective,
        required_elements=required[:6],
        writing_instructions=writing,
    )


def _pad_chapters_to_minimum(
    chapters: list[PlannerChapterPlan],
    *,
    digest_mode: str,
    shared_inputs: SharedInputs,
    user_prompt: str,
    subject: str,
) -> list[PlannerChapterPlan]:
    config = get_planner_mode_runtime_config(digest_mode)
    if len(chapters) >= config.min_chapters:
        return chapters

    existing_titles = {_text(chapter.title).casefold() for chapter in chapters}
    topics = [
        topic
        for topic in _topic_strings(shared_inputs, user_prompt=user_prompt, subject=subject)
        if topic.casefold() not in existing_titles
    ]
    if not topics:
        topics = [
            "核心概念总览",
            "关键结构与流程",
            "典型例题与应用",
            "易错点与复盘",
            "综合练习",
        ]

    padded = list(chapters)
    topic_index = 0
    while len(padded) < config.min_chapters:
        topic = topics[topic_index % len(topics)]
        topic_index += 1
        title_key = topic.casefold()
        if title_key in existing_titles:
            topic = f"{topic}（补充）"
            title_key = topic.casefold()
        existing_titles.add(title_key)
        padded.append(
            _build_supplement_chapter(
                index=len(padded) + 1,
                topic=topic,
                digest_mode=digest_mode,
                user_prompt=user_prompt,
            )
        )
    return padded


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
    user_prompt: str | None = None,
    user_goal: str | None = None,
    requested_digest_mode: str,
    shared_inputs: SharedInputs | None = None,
    latest_plan: BuildPlannerDraft | Mapping[str, Any] | None = None,
) -> BuildPlannerDraft:
    """把模型草稿规范化成稳定 Planner 合同。

    这里会校验章节、补齐最少章节数、统一 subject 展示名、生成 media plan
    和 build constraints。输出会被保存为 latest_plan，并最终冻结给 DocGen。
    """

    shared = shared_inputs or _minimal_shared_inputs(subject)
    resolved_user_prompt = _text(user_prompt or user_goal)
    current = _mapping(draft)
    previous = _mapping(latest_plan)
    mode = _normalize_digest_mode(requested_digest_mode or current.get("digest_mode") or previous.get("digest_mode"))
    display_subject = _resolve_subject_display_name(subject, shared_inputs=shared, user_prompt=resolved_user_prompt)

    current_chapters = _chapter_items(current.get("chapter_plan"))
    previous_chapters = _chapter_items(previous.get("chapter_plan"))
    raw_chapters = current_chapters or previous_chapters
    if not raw_chapters:
        raise ValueError("planner plan is missing chapters")

    chapters = [_merge_chapter(raw, index) for index, raw in enumerate(raw_chapters, start=1)]
    chapters = _pad_chapters_to_minimum(
        chapters,
        digest_mode=mode,
        shared_inputs=shared,
        user_prompt=resolved_user_prompt,
        subject=display_subject,
    )
    plan_summary = _text(current.get("plan_summary") or previous.get("plan_summary"))
    if not plan_summary:
        raise ValueError("planner plan is missing plan_summary")
    plan_steps = _strings(current.get("plan_steps") or previous.get("plan_steps"))

    return BuildPlannerDraft(
        subject=display_subject,
        user_prompt=resolved_user_prompt,
        digest_mode=mode,
        chapter_plan=chapters,
        build_constraints=_build_constraints(digest_mode=mode, chapter_count=len(chapters), shared_inputs=shared),
        plan_summary=plan_summary,
        plan_steps=plan_steps,
    )


def normalize_planner_payload(
    payload: BuildPlannerDraft | Mapping[str, Any] | None,
    *,
    subject: str,
    user_prompt: str | None = None,
    user_goal: str | None = None,
    requested_digest_mode: str,
    shared_inputs: SharedInputs | None = None,
    latest_plan: BuildPlannerDraft | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return normalize_planner_draft(
        payload,
        subject=subject,
        user_prompt=user_prompt,
        user_goal=user_goal,
        requested_digest_mode=requested_digest_mode,
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
