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
from app.workflows.digest.planner.lib.requested_structure import (
    extract_explicit_chapter_titles,
    extract_explicit_learning_topic,
    extract_requested_chapter_count,
)


class PlannerChapterPlan(BaseModel):
    chapter_index: int
    title: str
    objective: str = ""
    required_elements: list[str] = Field(default_factory=list)
    writing_instructions: str = ""


class PlannerDiagnosticQuestion(BaseModel):
    question: str
    purpose: str = ""
    options: list[str] = Field(default_factory=list)
    answer: str = ""


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
    diagnose_status: str = ""
    diagnose_note: str = ""
    build_constraints: dict[str, Any] = Field(default_factory=dict)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


_DIAGNOSIS_FEEDBACK_PREFIXES = (
    "前置诊断选择：",
    "前置诊断选择:",
    "跳过前置诊断，请按当前学习目标和资料继续生成可确认的学习方案。",
)
_DIAGNOSIS_METADATA_RE = re.compile(
    r"(?:用户最新调整[:：]\s*)?(?:前置诊断选择[:：]|跳过前置诊断，请按当前学习目标和资料继续生成可确认的学习方案。).*$",
    re.S,
)


def _is_diagnosis_feedback(value: str) -> bool:
    text = _text(value)
    return any(text.startswith(prefix) for prefix in _DIAGNOSIS_FEEDBACK_PREFIXES)


def _strip_diagnosis_metadata(value: Any) -> str:
    """Remove diagnosis-resolution chatter before parsing user-requested structure."""

    text = str(value or "").strip()
    if not text:
        return ""
    return _DIAGNOSIS_METADATA_RE.sub("", text).strip()


def _remove_planner_self_intro(text: str) -> str:
    return re.sub(
        r"^\s*(?:你好[！!。]?\s*)?我是你的\s*AITeachMe\s*学习规划师[。！!，,]?\s*",
        "",
        str(text or ""),
    )


def _student_facing_text(value: Any) -> str:
    return (
        _remove_planner_self_intro(_text(value))
        .replace("速成课模式", "紧凑节奏")
        .replace("速成课", "紧凑节奏")
        .replace("系统课", "系统节奏")
        .replace("章节合同", "学习大纲")
    )


def compose_effective_planner_request_text(user_prompt: Any, feedback_message: Any = "") -> str:
    """Combine the original goal and latest revision for structural parsing."""

    prompt = _text(user_prompt)
    feedback = _text(feedback_message)
    if _is_diagnosis_feedback(feedback):
        return prompt
    if not feedback:
        return prompt
    if not prompt:
        return feedback
    if feedback in prompt:
        return prompt
    return f"{prompt}\n用户最新调整：{feedback}"


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


def _required_elements(value: Any) -> list[str]:
    """Normalize model-provided chapter requirements without rewriting semantics."""

    return _strings(value)


def _validate_required_elements(elements: list[str], *, title: str) -> None:
    for element in elements:
        if len(element) > 120 or element.count("|") >= 3 or "```" in element:
            raise ValueError(
                f"planner chapter `{title}` contains a non-concise required_element"
            )


def _diagnosis_contract_text(value: Any, *, field: str = "text") -> str:
    del field
    return _student_facing_text(value)


def _ensure_four_diagnosis_options(value: Any) -> list[str]:
    """Validate the four-choice contract without rewriting model output."""

    options = _strings(value)
    return options if len(options) == 4 else []


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
def _compact_planner_chapter_title(title: str) -> str:
    """Remove numbering/quote formatting while preserving the model's title semantics."""

    return clean_generated_chapter_title(title)


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
                f"默认参考 {contract.min_chapters}-{contract.max_chapters} 章。"
                f"除非用户明确要求更短或资料确实只支持更少模块，通常不要少于 {contract.min_chapters} 章；"
                "章节数按真实学习路径灵活取舍。"
            ),
            (
                f"- 目标成稿长度：{contract.target_length}。这是整份知识文档的预算，"
                "仅用于判断章节颗粒度。"
            ),
            f"- 划分主线：{granularity}",
            "- 章节是可直接授课的内容模块，标题写成可独立理解的课程目录名，通常 4-12 字，不使用冒号/破折号副标题；过宽的目录词只补一个短学习焦点。",
            "- required_elements 只描述需要用户确认的覆盖范围，写成具体概念、方法、题型或易错对象；写作路径、资料落点、例题数量、练习和小测策略由 DocGen 决定。",
            "- required_elements 不得把“图示”“方法步骤”“单元测试”“讲后纠错与回顾”“为后续章节打底”等教学动作或泛容器当成独立知识点。",
            "- 每个 required_elements 必须是不超过 60 个汉字的短对象；禁止复制材料原文、代码、表格行、OCR 碎片或整段例题。",
            "- 用户以“按 A、B、C 划分章节/模块/单元”给出列表时，这个列表就是完整一级章节清单，chapters 与 A/B/C 逐项对应，数组长度等于列表项数量。",
            "- 用户给出的列表项已是清晰知识块名称时，标题等于该列表项；如果只是宽泛类别，可保留原词并补一个简短限定；进度预算写进 plan。",
            "- 用户同时给出学习天数和 A/B/C 列表时，天数是 A/B/C 的进度预算；最后一个知识块按它自身的具体对象、方法和练习安排展开。",
            "- 全程巩固、检测和纠错只需在 plan 中说明服务范围，不在 Planner 阶段展开逐章执行策略。",
            "- 每章承担一个主要学习任务，相邻章节体现依赖、递进或场景切换。",
            "- 标题用真实课程目录名：清楚直观，保留必要限定词，避免只有“函数”“几何”这类过短空标题，也避免“模块：目标/方法/应用”式长副标题。",
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
    explicit_topic = extract_explicit_learning_topic(user_prompt)
    if explicit_topic:
        return explicit_topic
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
    title = _compact_planner_chapter_title(_text(raw.get("title")))
    key_points = _required_elements(raw.get("required_elements") or raw.get("key_points"))
    objective = _student_facing_text(raw.get("objective"))
    writing_instructions = _student_facing_text(raw.get("writing_instructions"))
    if not title:
        raise ValueError(f"planner chapter #{index} is missing title")
    if not key_points:
        raise ValueError(f"planner chapter `{title}` is missing required_elements")
    _validate_required_elements(key_points, title=title)
    if not objective:
        raise ValueError(f"planner chapter `{title}` is missing objective")
    return PlannerChapterPlan(
        chapter_index=_positive_int(raw.get("chapter_index")) or index,
        title=title,
        objective=objective,
        required_elements=key_points,
        writing_instructions=writing_instructions,
    )


def _merge_diagnostic(raw: Mapping[str, Any]) -> PlannerDiagnosticQuestion | None:
    question = _diagnosis_contract_text(raw.get("question") or raw.get("title") or raw.get("prompt"), field="question")
    if not question:
        return None
    purpose = _diagnosis_contract_text(
        raw.get("purpose") or raw.get("diagnosis_target") or raw.get("target"),
        field="purpose",
    )
    options = _strings(
        raw.get("options")
        or raw.get("choices")
        or raw.get("sample_answers")
        or raw.get("quick_answers")
        or raw.get("example_answers")
        or raw.get("answers")
    )
    normalized_options = _ensure_four_diagnosis_options(options)
    if len(normalized_options) != 4:
        return None
    return PlannerDiagnosticQuestion(
        question=question,
        purpose=purpose,
        options=normalized_options,
        answer=_diagnosis_contract_text(raw.get("answer") or raw.get("user_answer") or raw.get("selected_answer")),
    )


def _normalize_diagnose(
    raw_items: list[dict[str, Any]],
    *,
    chapters: list[PlannerChapterPlan],
    user_prompt: str,
    digest_mode: str,
) -> list[PlannerDiagnosticQuestion]:
    del chapters, user_prompt, digest_mode

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
        result.append(
            item.model_copy(update={"options": _ensure_four_diagnosis_options(item.options)})
        )
        if len(result) >= 4:
            break
    return result[:4]


def normalize_planner_diagnosis_draft(
    draft: Mapping[str, Any] | None,
    *,
    course_id: str,
    user_prompt: str | None = None,
    requested_digest_mode: str,
    shared_inputs: SharedInputs | None = None,
    latest_plan: BuildPlannerDraft | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize the first-stage planner diagnosis payload without requiring chapters."""

    shared = shared_inputs or _minimal_shared_inputs(course_id)
    resolved_user_prompt = _text(_strip_diagnosis_metadata(user_prompt))
    current = _mapping(draft)
    previous = _mapping(latest_plan)
    mode = _normalize_digest_mode(requested_digest_mode or current.get("digest_mode") or previous.get("digest_mode"))
    display_course = (
        _text(current.get("course_name") or previous.get("course_name"))
        or extract_explicit_learning_topic(resolved_user_prompt)
        or _resolve_course_name(course_id, shared_inputs=shared, user_prompt=resolved_user_prompt)
    )
    diagnose = _normalize_diagnose(
        _diagnose_items(current.get("diagnose")) or _diagnose_items(previous.get("diagnose")),
        chapters=[],
        user_prompt=resolved_user_prompt,
        digest_mode=mode,
    )
    status = _text(current.get("diagnose_status") or previous.get("diagnose_status")) or "pending"
    if status not in {"pending", "answered", "skipped"}:
        status = "pending"
    if not diagnose and status == "pending":
        status = "skipped"
    return {
        "planner_stage": "diagnosis",
        "course_name": display_course,
        "course_icon": _text(current.get("course_icon") or previous.get("course_icon")),
        "user_prompt": resolved_user_prompt,
        "digest_mode": mode,
        "planning_note": _student_facing_text(current.get("planning_note") or previous.get("planning_note")),
        "suggestion": "",
        "plan": "",
        "chapters": [],
        "diagnose": [item.model_dump(mode="json") for item in diagnose],
        "diagnose_status": status,
        "diagnose_note": _student_facing_text(current.get("diagnose_note") or previous.get("diagnose_note")),
        "build_constraints": {},
    }


def _reindex_chapters(chapters: list[PlannerChapterPlan]) -> list[PlannerChapterPlan]:
    return [
        chapter.model_copy(update={"chapter_index": index})
        for index, chapter in enumerate(chapters, start=1)
    ]


def _dedupe_chapters_by_title(chapters: list[PlannerChapterPlan]) -> list[PlannerChapterPlan]:
    seen: set[str] = set()
    for chapter in chapters:
        key = _text(chapter.title).casefold()
        if key in seen:
            raise ValueError(f"planner contains duplicate chapter title `{chapter.title}`")
        seen.add(key)
    return _reindex_chapters(chapters)


def _normalize_chapter_count(
    chapters: list[PlannerChapterPlan],
    *,
    digest_mode: str,
    requested_chapter_count: int | None = None,
    requested_chapter_count_range: tuple[int, int] | None = None,
) -> list[PlannerChapterPlan]:
    chapters = _dedupe_chapters_by_title(chapters)
    if requested_chapter_count is not None:
        if len(chapters) != requested_chapter_count:
            raise ValueError(
                f"planner chapter count {len(chapters)} does not match requested {requested_chapter_count}"
            )
        return _reindex_chapters(chapters)
    if requested_chapter_count_range is not None:
        min_count, max_count = requested_chapter_count_range
        if not min_count <= len(chapters) <= max_count:
            raise ValueError(
                f"planner chapter count {len(chapters)} is outside requested range {min_count}-{max_count}"
            )
        return _reindex_chapters(chapters)
    return _reindex_chapters(chapters)


def _build_constraints(
    *,
    digest_mode: str,
    chapter_count: int,
    shared_inputs: SharedInputs,
    requested_chapter_count: int | None = None,
    requested_chapter_count_range: tuple[int, int] | None = None,
    overrides: Mapping[str, Any] | None = None,
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
        "chapter_length_profile": "standard",
        "chapter_min_words": 2400,
        "chapter_target_words": 3000,
        "chapter_max_words": 3600,
    }
    raw_overrides = _mapping(overrides)
    profile_defaults = {
        "outline": (1400, 1800, 2200),
        "standard": (2400, 3000, 3600),
        "detailed": (3400, 4200, 5000),
        "foundation": (4200, 5200, 6200),
    }
    profile = _text(raw_overrides.get("chapter_length_profile")).casefold()
    if profile not in profile_defaults:
        profile = "standard"
    default_min, default_target, default_max = profile_defaults[profile]
    chapter_min = _positive_int(raw_overrides.get("chapter_min_words")) or default_min
    chapter_target = _positive_int(raw_overrides.get("chapter_target_words")) or default_target
    chapter_max = _positive_int(raw_overrides.get("chapter_max_words")) or default_max
    if 800 <= chapter_min <= chapter_target <= chapter_max <= 8000:
        constraints.update(
            {
                "chapter_length_profile": profile,
                "chapter_min_words": chapter_min,
                "chapter_target_words": chapter_target,
                "chapter_max_words": chapter_max,
            }
        )
    target_total_words = _positive_int(raw_overrides.get("target_total_words"))
    if target_total_words is not None:
        constraints["target_total_words"] = target_total_words
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
    resolved_user_prompt = _text(_strip_diagnosis_metadata(user_prompt))
    current = _mapping(draft)
    previous = _mapping(latest_plan)
    current_constraints = {
        **_mapping(previous.get("build_constraints")),
        **_mapping(current.get("build_constraints")),
    }
    mode = _normalize_digest_mode(requested_digest_mode or current.get("digest_mode") or previous.get("digest_mode"))
    requested_chapter_titles = extract_explicit_chapter_titles(resolved_user_prompt)
    display_course = (
        _text(current.get("course_name") or previous.get("course_name"))
        or extract_explicit_learning_topic(resolved_user_prompt)
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
            if requested_chapter_count_range is None:
                requested_chapter_count = extract_requested_chapter_count(resolved_user_prompt)
    if requested_chapter_titles:
        requested_chapter_count = len(requested_chapter_titles)
        requested_chapter_count_range = None

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
    diagnose_status = _text(current.get("diagnose_status") or previous.get("diagnose_status"))
    diagnose_note = _student_facing_text(current.get("diagnose_note") or previous.get("diagnose_note"))
    diagnose = _normalize_diagnose(
        _diagnose_items(current.get("diagnose")) or _diagnose_items(previous.get("diagnose")),
        chapters=chapters,
        user_prompt=resolved_user_prompt,
        digest_mode=mode,
    )
    if diagnose and not diagnose_status:
        diagnose_status = "answered" if all(_text(item.answer) for item in diagnose) else "pending"

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
        diagnose_status=diagnose_status,
        diagnose_note=diagnose_note,
        build_constraints=_build_constraints(
            digest_mode=mode,
            chapter_count=len(chapters),
            shared_inputs=shared,
            requested_chapter_count=requested_chapter_count,
            requested_chapter_count_range=requested_chapter_count_range,
            overrides=current_constraints,
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
    "normalize_planner_diagnosis_draft",
    "normalize_planner_draft",
    "normalize_planner_payload",
    "planner_mode_label",
    "render_planner_chapter_contract",
    "compose_effective_planner_request_text",
]
