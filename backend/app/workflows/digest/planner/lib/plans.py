"""Normalize the planner's outline sketch into the stable plan payload."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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


class PlannerDiagnosticQuestion(BaseModel):
    question: str
    purpose: str = ""
    sample_answers: list[str] = Field(default_factory=list)


class BuildPlannerDraft(BaseModel):
    """Stable planner payload consumed by API and DocGen."""

    model_config = ConfigDict(populate_by_name=True)

    course_name: str = ""
    course_icon: str = ""
    user_prompt: str
    digest_mode: str = "systematic"
    planning_note: str = ""
    suggestion: str = ""
    plan: str = ""
    chapters: list[PlannerChapterPlan] = Field(default_factory=list)
    diagnose: list[PlannerDiagnosticQuestion] = Field(default_factory=list)
    build_constraints: dict[str, Any] = Field(default_factory=dict)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _student_facing_text(value: Any) -> str:
    return (
        _text(value)
        .replace("速成课模式", "紧凑节奏")
        .replace("速成课", "紧凑节奏")
        .replace("系统课", "系统节奏")
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


def _diagnose_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_mapping(item) for item in value]


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


_CHAPTER_COUNT_UNIT_PATTERN = r"(?:个\s*)?(?:章节|章)"
_CHAPTER_COUNT_RANGE_RE = re.compile(
    rf"(?<!\d)(?P<min>\d{{1,2}})\s*(?:[-~—–]|至|到)\s*(?P<max>\d{{1,2}})\s*{_CHAPTER_COUNT_UNIT_PATTERN}"
)


def _chapter_count_range_from_text(value: Any) -> tuple[int, int] | None:
    text = _text(value)
    match = _CHAPTER_COUNT_RANGE_RE.search(text)
    if not match:
        return None
    min_count = _positive_int(match.group("min"))
    max_count = _positive_int(match.group("max"))
    if min_count is None or max_count is None:
        return None
    if min_count > max_count:
        min_count, max_count = max_count, min_count
    if 1 <= min_count <= max_count <= 30:
        return (min_count, max_count)
    return None


def _normalize_digest_mode(value: Any) -> str:
    return normalize_planner_mode(value, default=get_teaching_runtime_config().planner.default_digest_mode)


def planner_mode_label(value: Any) -> str:
    return "紧凑节奏" if _normalize_digest_mode(value) == "sprint" else "系统节奏"


def compose_planning_note(*items: Any) -> str:
    """Collapse planner understanding artifacts into one user-facing note."""

    parts = _strings(items)
    return "\n".join(parts[:2])


def render_planner_chapter_contract(value: Any) -> str:
    """Render the high-priority chapter planning contract for Planner prompts."""

    mode = _normalize_digest_mode(value)
    contract = get_planner_mode_contract(mode)
    if mode == "sprint":
        granularity = "按具体知识对象、方法模块、典型题型和易错边界划分。"
    else:
        granularity = "按概念依赖、知识对象、方法结构和应用场景划分。"
    return "\n".join(
        [
            "章节规划合同：",
            f"- 模式：{planner_mode_label(mode)}。",
            (
                f"- 章节数量：由用户目标、资料复杂度和学习路径决定；"
                f"默认参考 {contract.min_chapters}-{contract.max_chapters} 章，"
                "按真实学习路径取舍。"
            ),
            (
                f"- 目标成稿长度：{contract.target_length}。这是整份知识文档的预算，"
                "仅用于判断章节颗粒度。"
            ),
            f"- 划分主线：{granularity}",
            "- 章节是可直接授课的内容模块，聚焦具体知识对象、方法步骤、题型技能或应用场景。",
            "- 例题、练习、检测、纠错和巩固是章节内部的学习活动，放进对应模块的 required_elements/key_points。",
            "- 用户以“按 A、B、C 划分章节/模块/单元”给出列表时，这个列表就是完整一级章节清单，chapters 与 A/B/C 逐项对应，数组长度等于列表项数量。",
            "- 用户给出的列表项已是知识块名称时，标题等于该列表项；学习动作、周期和训练安排写进 required_elements/key_points。",
            "- 用户同时给出学习天数和 A/B/C 列表时，天数是 A/B/C 的进度预算，末尾时间仍落到最后一个知识块的具体对象、方法和练习安排。",
            "- 每章承担一个主要学习任务，相邻章节体现依赖、递进或场景切换。",
            "- 标题用真实讲义目录名：清楚直观优先，保留必要限定词；细节枚举放到 required_elements/key_points。",
            "- 用户列出的额外学习活动也按其服务的内容模块安排，形成讲解、例题、练习、小测的章内闭环。",
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


def _merge_diagnostic(raw: Mapping[str, Any]) -> PlannerDiagnosticQuestion | None:
    question = _student_facing_text(raw.get("question") or raw.get("title") or raw.get("prompt"))
    if not question:
        return None
    purpose = _student_facing_text(raw.get("purpose") or raw.get("diagnosis_target") or raw.get("target"))
    sample_answers = _strings(
        raw.get("sample_answers")
        or raw.get("quick_answers")
        or raw.get("example_answers")
        or raw.get("answers")
    )[:4]
    if not sample_answers:
        sample_answers = ["我能独立讲清楚", "看例题能跟上", "这里还比较陌生"]
    return PlannerDiagnosticQuestion(
        question=question,
        purpose=purpose,
        sample_answers=sample_answers,
    )


def _fallback_diagnostic_pool(
    *,
    chapters: list[PlannerChapterPlan],
    user_prompt: str,
    digest_mode: str,
) -> list[PlannerDiagnosticQuestion]:
    mode_label = planner_mode_label(digest_mode)
    result: list[PlannerDiagnosticQuestion] = []
    for chapter in chapters[:10]:
        points = _strings(chapter.required_elements)[:2]
        focus_text = "、".join(points) if points else chapter.objective
        sample_answers = [
            f"我能说清{points[0]}" if points else "我能讲清本章核心概念",
            f"我会做基础题，但{points[1]}还不稳" if len(points) > 1 else "看例题能跟上，独立做题不稳",
            "这一块基本没学过",
        ]
        result.append(
            PlannerDiagnosticQuestion(
                question=f"看到“{chapter.title}”这一部分，你现在最有把握和最卡住的点分别是什么？",
                purpose=f"识别{chapter.title}的已有掌握度和薄弱入口。",
                sample_answers=sample_answers,
            )
        )

    generic_items = [
        (
            f"你希望这门课更偏{mode_label}拿分、理解推导，还是实际应用？",
            "校准知识文档的讲解深度和例题密度。",
            ["先应付考试", "想真正理解", "要能完成作业/项目"],
        ),
        (
            "最近一次接触这个主题时，你是卡在概念、公式步骤、题型迁移，还是时间不够？",
            "识别后续考试和伴读的优先补救方向。",
            ["概念不清", "步骤会忘", "题目一变就不会", "时间不够"],
        ),
        (
            "如果现在让你做一组 10 分钟小测，你预计正确率大概是多少？",
            "给 Profile 初始掌握度一个自评锚点。",
            ["80% 以上", "50%-80%", "低于 50%", "完全没底"],
        ),
        (
            "你更想先补哪类内容：基础定义、典型例题、易错辨析，还是综合训练？",
            "决定 DocGen 章节内部的内容排序。",
            ["基础定义", "典型例题", "易错辨析", "综合训练"],
        ),
        (
            "你希望 AI 后续解释时更像老师推导、考前提纲，还是错题教练？",
            "把诊断偏好传给伴读和画像链路。",
            ["老师推导", "考前提纲", "错题教练"],
        ),
    ]
    for question, purpose, sample_answers in generic_items:
        result.append(
            PlannerDiagnosticQuestion(
                question=question,
                purpose=purpose,
                sample_answers=sample_answers,
            )
        )
        if len(result) >= 10:
            break
    while len(result) < 10:
        index = len(result) + 1
        scope = _text(user_prompt) or "当前主题"
        result.append(
            PlannerDiagnosticQuestion(
                question=f"关于{scope}，第 {index} 个你最想确认自己是否掌握的点是什么？",
                purpose="补齐前置诊断题数量，收集学习者自评边界。",
                sample_answers=["已经掌握", "需要例题", "需要从头讲"],
            )
        )
    return result[:10]


def _normalize_diagnose(
    raw_items: list[dict[str, Any]],
    *,
    chapters: list[PlannerChapterPlan],
    user_prompt: str,
    digest_mode: str,
) -> list[PlannerDiagnosticQuestion]:
    result: list[PlannerDiagnosticQuestion] = []
    seen: set[str] = set()
    for raw in raw_items:
        item = _merge_diagnostic(raw)
        if item is None:
            continue
        key = _text(item.question).casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= 10:
            break
    if result:
        return result
    return _fallback_diagnostic_pool(
        chapters=chapters,
        user_prompt=user_prompt,
        digest_mode=digest_mode,
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


def _cap_chapters_to_limit(
    chapters: list[PlannerChapterPlan],
    *,
    chapter_limit: int,
    note_prefix: str,
) -> list[PlannerChapterPlan]:
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
            note_prefix=note_prefix,
        )
    return _reindex_chapters(kept)


def _cap_chapters_to_maximum(
    chapters: list[PlannerChapterPlan],
    *,
    digest_mode: str,
) -> list[PlannerChapterPlan]:
    contract = get_planner_mode_contract(digest_mode)
    return _cap_chapters_to_limit(
        chapters,
        chapter_limit=max(contract.min_chapters, contract.max_chapters),
        note_prefix="超出章节预算后合并覆盖",
    )


def _normalize_chapter_count(
    chapters: list[PlannerChapterPlan],
    *,
    digest_mode: str,
    requested_chapter_count: int | None = None,
    requested_chapter_count_range: tuple[int, int] | None = None,
) -> list[PlannerChapterPlan]:
    if requested_chapter_count is not None:
        if len(chapters) != requested_chapter_count:
            raise ValueError(
                f"planner chapter count {len(chapters)} does not match requested {requested_chapter_count}"
            )
        return _reindex_chapters(chapters)
    chapters = _dedupe_chapters_by_title(chapters)
    if requested_chapter_count_range is not None:
        _min_count, max_count = requested_chapter_count_range
        chapters = _cap_chapters_to_limit(
            chapters,
            chapter_limit=max_count,
            note_prefix="超出用户章节范围后合并覆盖",
        )
        return _reindex_chapters(chapters)
    chapters = _cap_chapters_to_maximum(chapters, digest_mode=digest_mode)
    return _reindex_chapters(chapters)


def _build_constraints(
    *,
    digest_mode: str,
    chapter_count: int,
    shared_inputs: SharedInputs,
    requested_chapter_count: int | None = None,
    requested_chapter_count_range: tuple[int, int] | None = None,
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
    elif requested_chapter_count_range is not None:
        min_count, max_count = requested_chapter_count_range
        constraints["requested_chapter_min"] = min_count
        constraints["requested_chapter_max"] = max_count
        constraints["chapter_count_source"] = "user_request_range"
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
    display_course = (
        _text(current.get("course_name") or previous.get("course_name"))
        or _resolve_course_name(course_id, shared_inputs=shared, user_prompt=resolved_user_prompt)
    )
    requested_chapter_count = _positive_int(current_constraints.get("requested_chapter_count"))
    requested_chapter_count_range: tuple[int, int] | None = None
    if requested_chapter_count is None:
        requested_min = _positive_int(current_constraints.get("requested_chapter_min"))
        requested_max = _positive_int(current_constraints.get("requested_chapter_max"))
        if requested_min is not None and requested_max is not None:
            requested_chapter_count_range = (min(requested_min, requested_max), max(requested_min, requested_max))
        else:
            requested_chapter_count_range = _chapter_count_range_from_text(resolved_user_prompt)

    current_chapters = _chapter_items(current.get("chapters"))
    previous_chapters = _chapter_items(previous.get("chapters"))
    raw_chapters = current_chapters or previous_chapters
    if not raw_chapters:
        raise ValueError("planner plan is missing chapters")

    chapters = [_merge_chapter(raw, index) for index, raw in enumerate(raw_chapters, start=1)]
    chapters = _normalize_chapter_count(
        chapters,
        digest_mode=mode,
        requested_chapter_count=requested_chapter_count,
        requested_chapter_count_range=requested_chapter_count_range,
    )
    plan_text = _student_facing_text(current.get("plan") or previous.get("plan"))
    if not plan_text:
        raise ValueError("planner plan is missing plan")
    suggestion = _student_facing_text(current.get("suggestion") or previous.get("suggestion"))
    planning_note = _student_facing_text(current.get("planning_note") or previous.get("planning_note"))
    course_icon = _text(current.get("course_icon") or previous.get("course_icon"))
    diagnose = _normalize_diagnose(
        _diagnose_items(current.get("diagnose")) or _diagnose_items(previous.get("diagnose")),
        chapters=chapters,
        user_prompt=resolved_user_prompt,
        digest_mode=mode,
    )

    return BuildPlannerDraft(
        course_name=display_course,
        course_icon=course_icon,
        user_prompt=resolved_user_prompt,
        digest_mode=mode,
        planning_note=planning_note,
        suggestion=suggestion,
        plan=plan_text,
        chapters=chapters,
        diagnose=diagnose,
        build_constraints=_build_constraints(
            digest_mode=mode,
            chapter_count=len(chapters),
            shared_inputs=shared,
            requested_chapter_count=requested_chapter_count,
            requested_chapter_count_range=requested_chapter_count_range,
        ),
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
    "PlannerDiagnosticQuestion",
    "compose_planning_note",
    "_resolve_course_name",
    "normalize_planner_draft",
    "normalize_planner_payload",
    "planner_mode_label",
    "render_planner_chapter_contract",
]
