"""Normalize the planner's outline sketch into the stable plan payload."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.workflows.digest.common.pedagogy import clean_generated_chapter_title
from app.workflows.digest.common.runtime_config import get_teaching_runtime_config
from app.workflows.digest.common.models import FastTopicHints, SharedInputs, CourseProfile
from app.workflows.digest.planner.lib.constants import get_planner_mode_contract, normalize_planner_mode


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
    adjustment_questions: list[str] = Field(default_factory=list)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _student_facing_text(value: Any) -> str:
    return (
        _text(value)
        .replace("速成课模式", "快速复习节奏")
        .replace("速成课", "快速复习")
        .replace("系统课", "系统学习")
        .replace("章节合同", "学习大纲")
    )


def _strings(value: Any) -> list[str]:
    items = value if isinstance(value, (list, tuple, set)) else [value]
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _student_facing_text(item)
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
    return normalize_planner_mode(value, default=get_teaching_runtime_config().planner.default_digest_mode)


def planner_mode_label(value: Any) -> str:
    return "快速复习" if _normalize_digest_mode(value) == "sprint" else "系统学习"


def render_planner_chapter_contract(value: Any) -> str:
    """Render the high-priority chapter planning contract for Planner prompts."""

    mode = _normalize_digest_mode(value)
    contract = get_planner_mode_contract(mode)
    if mode == "sprint":
        granularity = "按短期可执行的复习任务、常见任务/题型、易错边界和回看节奏划分。"
    else:
        granularity = "按概念依赖、知识对象、方法结构、应用迁移和综合收束划分。"
    return "\n".join(
        [
            "章节规划合同：",
            f"- 模式：{planner_mode_label(mode)}。",
            (
                f"- 章节数量：由用户目标、资料复杂度和学习路径决定；"
                f"默认参考 {contract.min_chapters}-{contract.max_chapters} 章，"
                "不要为了凑默认数量额外加空心章节，也不要拆得过碎。"
            ),
            (
                f"- 目标成稿长度：{contract.target_length}。这是整份知识文档的预算，"
                "用于判断章节颗粒度，不要写进章节标题或正文承诺。"
            ),
            f"- 划分主线：{granularity}",
            "- 每章只能承担一个主要学习任务；相邻章节要有清楚的前后依赖、能力递进或场景切换。",
            "- 不要按文件名、页码、资料来源、PPT 顺序机械切章；要按学习者真正需要建立的理解路径切章。",
            "- 不要把同一个知识对象拆成多个空心章节，也不要把多个独立主题硬塞进一个大杂烩章节。",
            "- 章节标题要能回答“这一章到底帮我学会什么/解决什么问题”。",
            "- 章节标题要短，通常 4-12 个中文字符；不使用冒号副标题、分号说明或长串枚举，细节放到 required_elements/key_points。",
            "- 章节标题要自然像真实讲义目录，避免口号化、过度对仗或统一句式。",
        ]
    )


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
    title = clean_generated_chapter_title(_text(raw.get("title")))
    key_points = _strings(raw.get("required_elements") or raw.get("key_points"))
    if not title:
        raise ValueError(f"planner chapter #{index} is missing title")
    if not key_points:
        raise ValueError(f"planner chapter `{title}` is missing key_points")
    return PlannerChapterPlan(
        chapter_index=_positive_int(raw.get("chapter_index")) or index,
        title=title,
        objective=_student_facing_text(raw.get("objective")) or "；".join(key_points),
        required_elements=key_points,
        writing_instructions=_student_facing_text(raw.get("writing_instructions")) or "围绕本章知识点生成清晰讲解。",
    )


def _reindex_chapters(chapters: list[PlannerChapterPlan]) -> list[PlannerChapterPlan]:
    return [
        chapter.model_copy(update={"chapter_index": index})
        for index, chapter in enumerate(chapters, start=1)
    ]


def _merge_chapter_into(
    base: PlannerChapterPlan,
    extra: PlannerChapterPlan,
    *,
    note_prefix: str,
) -> PlannerChapterPlan:
    extra_title = _text(extra.title)
    note = f"{note_prefix}：{extra_title}" if extra_title else ""
    required = _strings([*base.required_elements, note, *extra.required_elements])[:10]
    objective_parts = _strings(
        [
            base.objective,
            f"同时吸收《{extra_title}》中的相邻内容。" if extra_title else extra.objective,
        ]
    )
    writing_parts = _strings(
        [
            base.writing_instructions,
            f"同时处理《{extra_title}》的相邻内容，保持边界清楚，避免重复展开。" if extra_title else "",
        ]
    )
    return base.model_copy(
        update={
            "objective": "；".join(objective_parts[:3]),
            "required_elements": required,
            "writing_instructions": " ".join(writing_parts[:2]),
        }
    )


def _dedupe_chapters_by_title(chapters: list[PlannerChapterPlan]) -> list[PlannerChapterPlan]:
    result: list[PlannerChapterPlan] = []
    title_positions: dict[str, int] = {}
    for chapter in chapters:
        key = _text(chapter.title).casefold()
        if key and key in title_positions:
            position = title_positions[key]
            result[position] = _merge_chapter_into(
                result[position],
                chapter,
                note_prefix="重复章节合并",
            )
            continue
        if key:
            title_positions[key] = len(result)
        result.append(chapter)
    return _reindex_chapters(result)


def _cap_chapters_to_maximum(
    chapters: list[PlannerChapterPlan],
    *,
    digest_mode: str,
) -> list[PlannerChapterPlan]:
    contract = get_planner_mode_contract(digest_mode)
    chapter_limit = max(contract.min_chapters, contract.max_chapters)
    if len(chapters) <= chapter_limit:
        return _reindex_chapters(chapters)

    kept = list(chapters[:chapter_limit])
    overflow = chapters[chapter_limit:]
    if not kept:
        return []
    for extra in overflow:
        kept[-1] = _merge_chapter_into(
            kept[-1],
            extra,
            note_prefix="超出章节预算后合并覆盖",
        )
    return _reindex_chapters(kept)


def _normalize_chapter_count(
    chapters: list[PlannerChapterPlan],
    *,
    digest_mode: str,
    requested_chapter_count: int | None = None,
) -> list[PlannerChapterPlan]:
    if requested_chapter_count is not None:
        if len(chapters) != requested_chapter_count:
            raise ValueError(
                f"planner chapter count {len(chapters)} does not match requested {requested_chapter_count}"
            )
        return _reindex_chapters(chapters)
    chapters = _dedupe_chapters_by_title(chapters)
    chapters = _cap_chapters_to_maximum(chapters, digest_mode=digest_mode)
    return _reindex_chapters(chapters)


def _build_constraints(
    *,
    digest_mode: str,
    chapter_count: int,
    shared_inputs: SharedInputs,
    requested_chapter_count: int | None = None,
) -> dict[str, Any]:
    contract = get_planner_mode_contract(digest_mode)
    constraints = {
        "min_chapters": chapter_count,
        "max_chapters": chapter_count,
        "target_chapter_count": chapter_count,
        "recommended_min_chapters": contract.min_chapters,
        "recommended_max_chapters": contract.max_chapters,
        "target_length": contract.target_length,
        "include_exercises": True,
        "include_sources": False,
        "math_mode": shared_inputs.course_profile.has_heavy_formulas,
    }
    if requested_chapter_count is not None:
        constraints["requested_chapter_count"] = requested_chapter_count
        constraints["chapter_count_source"] = "user_request"
    return constraints


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

    这里会校验章节、统一 course 展示名，并把模型生成的章节数冻结进
    build constraints。输出会被保存为 latest_plan，并最终冻结给 DocGen。
    """

    shared = shared_inputs or _minimal_shared_inputs(course_id)
    resolved_user_prompt = _text(user_prompt)
    current = _mapping(draft)
    previous = _mapping(latest_plan)
    current_constraints = _mapping(current.get("build_constraints"))
    mode = _normalize_digest_mode(requested_digest_mode or current.get("digest_mode") or previous.get("digest_mode"))
    display_course = _resolve_course_name(course_id, shared_inputs=shared, user_prompt=resolved_user_prompt)
    requested_chapter_count = _positive_int(current_constraints.get("requested_chapter_count"))

    current_chapters = _chapter_items(current.get("chapter_plan"))
    previous_chapters = _chapter_items(previous.get("chapter_plan"))
    raw_chapters = current_chapters or previous_chapters
    if not raw_chapters:
        raise ValueError("planner plan is missing chapters")

    chapters = [_merge_chapter(raw, index) for index, raw in enumerate(raw_chapters, start=1)]
    chapters = _normalize_chapter_count(
        chapters,
        digest_mode=mode,
        requested_chapter_count=requested_chapter_count,
    )
    plan_summary = _student_facing_text(current.get("plan_summary") or previous.get("plan_summary"))
    if not plan_summary:
        raise ValueError("planner plan is missing plan_summary")
    plan_steps = _strings(current.get("plan_steps") or previous.get("plan_steps"))
    adjustment_questions = _strings(current.get("adjustment_questions") or previous.get("adjustment_questions"))

    return BuildPlannerDraft(
        course_name=display_course,
        user_prompt=resolved_user_prompt,
        digest_mode=mode,
        chapter_plan=chapters,
        build_constraints=_build_constraints(
            digest_mode=mode,
            chapter_count=len(chapters),
            shared_inputs=shared,
            requested_chapter_count=requested_chapter_count,
        ),
        plan_summary=plan_summary,
        plan_steps=plan_steps,
        adjustment_questions=adjustment_questions,
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
    "normalize_planner_draft",
    "normalize_planner_payload",
    "planner_mode_label",
    "render_planner_chapter_contract",
]
