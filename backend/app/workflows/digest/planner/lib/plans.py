"""Normalize the planner's outline sketch into the stable plan payload."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.workflows.digest.common.runtime_config import get_planner_mode_runtime_config, get_teaching_runtime_config
from app.workflows.digest.common.models import FastTopicHints, SharedInputs, CourseProfile


class PlannerChapterPlan(BaseModel):
    chapter_index: int
    title: str
    objective: str = ""
    required_elements: list[str] = Field(default_factory=list)
    writing_instructions: str = ""


class BuildPlannerDraft(BaseModel):
    """Stable planner payload consumed by API and DocGen."""

    model_config = ConfigDict(populate_by_name=True)

    course_name: str = Field(default="", validation_alias=AliasChoices("course_name", "course"))
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


def _topic_strings(shared_inputs: SharedInputs, *, user_prompt: str, course_name: str) -> list[str]:
    course_hint = _text(course_name)
    values: list[Any] = [
        *shared_inputs.fast_hints.chapter_candidates,
        *[name for name, _count in shared_inputs.fast_hints.high_freq_terms],
        *shared_inputs.course_profile.key_topics,
        shared_inputs.course_profile.sub_discipline,
        shared_inputs.course_profile.discipline,
        user_prompt,
        course_hint,
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


def planner_mode_label(value: Any) -> str:
    return "冲刺型" if _normalize_digest_mode(value) == "sprint" else "系统型"


def _compact_supplement_title(value: Any, *, index: int, max_chars: int = 18) -> str:
    text = _text(value)
    for piece in re.split(r"[，,、/／：:；;。！？!?\n]+", text):
        cleaned = _text(piece).strip(" -—_")
        if 2 <= len(cleaned) <= max_chars:
            return cleaned
    if text:
        return text[:max_chars].rstrip(" ：:，,。；;|-")
    return f"补充章节 {index}"


def _minimal_shared_inputs(course_id: str) -> SharedInputs:
    return SharedInputs(
        fast_hints=FastTopicHints(),
        course_profile=CourseProfile(course_id=course_id, course_name=""),
    )


def _resolve_course_name(
    course_id: str,
    *,
    shared_inputs: SharedInputs | None,
    user_prompt: str = "",
) -> str:
    shared = shared_inputs or _minimal_shared_inputs(course_id)
    for candidate in [
        shared.course_profile.sub_discipline,
        shared.course_profile.discipline,
        *shared.fast_hints.chapter_candidates[:3],
        *shared.course_profile.key_topics[:3],
        user_prompt,
        course_id if not re.match(r"^(?:course|subj)_[a-z0-9]+$", _text(course_id), re.IGNORECASE) else "",
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
    return PlannerChapterPlan.model_validate(
        build_supplement_chapter_payload(
            index=index,
            topic=topic,
            digest_mode=digest_mode,
            user_prompt=user_prompt,
        )
    )


def build_supplement_chapter_payload(
    *,
    index: int,
    topic: str,
    digest_mode: str,
    user_prompt: str = "",
) -> dict[str, Any]:
    title = _compact_supplement_title(topic, index=index)
    normalized_mode = _normalize_digest_mode(digest_mode)
    if normalized_mode == "sprint":
        required = _strings([f"{title} 的常见任务/题型", f"{title} 的快速抓手", f"{title} 的易错边界"])
        objective = f"把《{title}》整理成能快速定位、练习和查漏的任务主线。"
        writing = "按冲刺型写法组织：先给判断抓手，再讲典型任务/题型和易错边界。"
    else:
        required = _strings([f"{title} 的核心对象", f"{title} 的结构关系", f"{title} 的例子与迁移"])
        objective = f"系统讲清《{title}》的概念边界、结构关系和典型应用。"
        writing = "按系统型写法组织：先讲对象和结构，再展开推理、例子与迁移。"
    if user_prompt:
        required = _strings([*required, f"{title} 与用户目标的连接"])
    return {
        "chapter_index": index,
        "title": title,
        "objective": objective,
        "required_elements": required[:6],
        "writing_instructions": writing,
    }


def _pad_chapters_to_minimum(
    chapters: list[PlannerChapterPlan],
    *,
    digest_mode: str,
    shared_inputs: SharedInputs,
    user_prompt: str,
    course_name: str,
) -> list[PlannerChapterPlan]:
    config = get_planner_mode_runtime_config(digest_mode)
    if len(chapters) >= config.min_chapters:
        return chapters

    existing_titles = {_text(chapter.title).casefold() for chapter in chapters}
    topics = [
        topic
        for topic in _topic_strings(shared_inputs, user_prompt=user_prompt, course_name=course_name)
        if topic.casefold() not in existing_titles
    ]
    if not topics:
        topics = [
            "学习边界与主线",
            "关键对象与关系",
            "方法应用与例子",
            "易错边界与复盘",
            "综合迁移任务",
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
        "include_sources": False,
        "math_mode": shared_inputs.course_profile.has_heavy_formulas,
    }


def normalize_planner_draft(
    draft: BuildPlannerDraft | Mapping[str, Any] | None,
    *,
    course_id: str,
    user_prompt: str | None = None,
    requested_digest_mode: str,
    shared_inputs: SharedInputs | None = None,
    latest_plan: BuildPlannerDraft | Mapping[str, Any] | None = None,
) -> BuildPlannerDraft:
    """把模型草稿规范化成稳定 Planner 合同。

    这里会校验章节、补齐最少章节数、统一 course 展示名、生成 media plan
    和 build constraints。输出会被保存为 latest_plan，并最终冻结给 DocGen。
    """

    shared = shared_inputs or _minimal_shared_inputs(course_id)
    resolved_user_prompt = _text(user_prompt)
    current = _mapping(draft)
    previous = _mapping(latest_plan)
    mode = _normalize_digest_mode(requested_digest_mode or current.get("digest_mode") or previous.get("digest_mode"))
    display_course = _resolve_course_name(course_id, shared_inputs=shared, user_prompt=resolved_user_prompt)

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
        course_name=display_course,
    )
    plan_summary = _text(current.get("plan_summary") or previous.get("plan_summary"))
    if not plan_summary:
        raise ValueError("planner plan is missing plan_summary")
    plan_steps = _strings(current.get("plan_steps") or previous.get("plan_steps"))

    return BuildPlannerDraft(
        course_name=display_course,
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
    course_id: str,
    user_prompt: str | None = None,
    requested_digest_mode: str,
    shared_inputs: SharedInputs | None = None,
    latest_plan: BuildPlannerDraft | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return normalize_planner_draft(
        payload,
        course_id=course_id,
        user_prompt=user_prompt,
        requested_digest_mode=requested_digest_mode,
        shared_inputs=shared_inputs,
        latest_plan=latest_plan,
    ).model_dump(mode="json")


__all__ = [
    "BuildPlannerDraft",
    "PlannerChapterPlan",
    "_resolve_course_name",
    "build_supplement_chapter_payload",
    "normalize_planner_draft",
    "normalize_planner_payload",
    "planner_mode_label",
]
