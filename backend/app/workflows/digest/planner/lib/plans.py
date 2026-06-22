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


_DIAGNOSIS_OPTION_FALLBACKS = [
    "先补基础",
    "例题带路",
    "多练变式",
    "章末小测",
    "错因提醒",
    "重点速查",
]


def _diagnosis_contract_text(value: Any, *, field: str = "text") -> str:
    text = _student_facing_text(value)
    if not text:
        return ""
    if field == "question" and "图示" in text and any(marker in text for marker in ("辅助", "重点", "怎么", "如何", "需求")):
        return "解析要多细？"
    replacements = {
        "图示辅助": "错因提醒",
        "图示重点": "解析重点",
        "图示需求": "解析需求",
        "多用图示": "多练变式",
        "少用图示": "只给要点",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    if field == "purpose":
        text = text.replace("图示", "解析")
    elif text == "图示":
        text = "解析"
    return text


def _ensure_four_diagnosis_options(value: Any) -> list[str]:
    """Keep planner diagnostics as real four-choice questions."""

    options = _strings(value)
    result: list[str] = []
    seen: set[str] = set()
    for item in [*options, *_DIAGNOSIS_OPTION_FALLBACKS]:
        text = _diagnosis_contract_text(item)
        if not text:
            continue
        if len(text) > 16:
            text = text[:16].rstrip(" ，,。；;、")
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= 4:
            break
    return result


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
_TITLE_DETAIL_SEPARATOR_RE = re.compile(r"\s*[:：\-—–]\s*", re.ASCII)
_MIDDLE_SCHOOL_MODULE_TITLE_MAP = {
    "数与式": "实数与代数式化简",
    "方程与不等式": "方程与不等式求解",
    "函数": "函数图像与解析式",
    "几何": "几何图形与证明",
    "统计与概率": "数据分析与概率应用",
}


def _compact_planner_chapter_title(title: str) -> str:
    """Keep planner chapter titles readable without collapsing them to vague tags."""

    cleaned = clean_generated_chapter_title(title)
    if not cleaned:
        return ""
    if len(cleaned) <= 14 and not _TITLE_DETAIL_SEPARATOR_RE.search(cleaned):
        return cleaned

    head, *tail = _TITLE_DETAIL_SEPARATOR_RE.split(cleaned, maxsplit=1)
    head = clean_generated_chapter_title(head)
    detail = clean_generated_chapter_title(tail[0]) if tail else ""
    if not head:
        return cleaned

    mapped = _MIDDLE_SCHOOL_MODULE_TITLE_MAP.get(head)
    if mapped:
        return mapped
    if len(head) >= 4 and any(token in head for token in ("与", "和", "及")):
        return head[:14]
    if len(head) >= 4 and len(head) <= 14:
        return head
    if len(head) <= 3 and detail:
        if "图像" in detail and "解析" in detail:
            return f"{head}图像与解析"[:14]
        if "证明" in detail:
            return f"{head}图形与证明"[:14]
        for token in ("基础", "性质", "方法", "应用", "计算"):
            if token in detail:
                return f"{head}{token}"[:14]
    return cleaned[:18] if len(cleaned) > 18 else cleaned


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
            "- required_elements/key_points 描述所属章节内部的目标、概念、例题、易错点、练习、检测、纠错和巩固安排。",
            "- required_elements/key_points 中的知识对象必须具体：写成概念名、方法名、题型名或错因名；不要把“图示”“方法步骤”“单元测试”“讲后纠错与回顾”“为后续章节打底”当成独立要点。图示/小测/纠错需求要落成具体对象，例如“函数图像读图”“函数值求解例题”“自变量与因变量混淆”“函数综合练习题型”。",
            "- 用户以“按 A、B、C 划分章节/模块/单元”给出列表时，这个列表就是完整一级章节清单，chapters 与 A/B/C 逐项对应，数组长度等于列表项数量。",
            "- 用户给出的列表项已是清晰知识块名称时，标题等于该列表项；如果只是宽泛类别，可保留原词并补一个简短限定；进度、训练和检测安排写进 required_elements/key_points。",
            "- 用户同时给出学习天数和 A/B/C 列表时，天数是 A/B/C 的进度预算；最后一个知识块按它自身的具体对象、方法和练习安排展开。",
            "- 全程巩固、检测和纠错按服务对象拆入各章节；方案说明结尾落到最后一个知识块自身的学习内容。",
            "- 每章承担一个主要学习任务，相邻章节体现依赖、递进或场景切换。",
            "- 标题用真实课程目录名：清楚直观，保留必要限定词，避免只有“函数”“几何”这类过短空标题，也避免“模块：目标/方法/应用”式长副标题；细节、时间预算、练习和检测安排放到 required_elements/key_points。",
            "- 用户列出的额外学习活动也按其服务的内容模块安排，形成讲解、例题、练习、小测的章内闭环；最后一个知识块的检测也围绕自身题型和易错点。",
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
    return PlannerDiagnosticQuestion(
        question=question,
        purpose=purpose,
        options=_ensure_four_diagnosis_options(options),
        answer=_diagnosis_contract_text(raw.get("answer") or raw.get("user_answer") or raw.get("selected_answer")),
    )


def _fallback_diagnostic_pool(
    *,
    chapters: list[PlannerChapterPlan],
    user_prompt: str,
    digest_mode: str,
) -> list[PlannerDiagnosticQuestion]:
    mode_label = planner_mode_label(digest_mode)
    generic_items = [
        (
            "当前基础怎样？",
            "文档落点：决定讲解起点、概念铺垫长度和例题难度。",
            [
                "零基础入门",
                "基础需补课",
                "中等求稳固",
                "基础扎实",
            ],
        ),
        (
            "讲解重心放哪？",
            "文档落点：决定正文讲解顺序、例题类型和每章小结。",
            [
                "概念先讲清",
                "例题带理解",
                "步骤拆细些",
                "易错多提醒",
            ],
        ),
        (
            "练习密度多大？",
            "文档落点：决定正文短练习、章末单元测试和解析密度。",
            [
                "少量精练",
                "每节小练",
                "章末小测",
                "多练变式",
            ],
        ),
        (
            "解析要多细？",
            "文档落点：决定文档内例题、随堂练习和章末小测的答案要点、步骤依据和错因提示。",
            [
                "只给要点",
                "写清依据",
                "补错因提醒",
                "补变式题",
            ],
        ),
    ]
    result: list[PlannerDiagnosticQuestion] = []
    for question, purpose, options in generic_items:
        result.append(
            PlannerDiagnosticQuestion(
                question=question,
                purpose=purpose,
                options=_ensure_four_diagnosis_options(options),
            )
        )
        if len(result) >= 4:
            break
    return result[:4]


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
        result.append(
            item.model_copy(update={"options": _ensure_four_diagnosis_options(item.options)})
        )
        if len(result) >= 4:
            break
    if result:
        if len(result) >= 4:
            return result[:4]
        fallback = _fallback_diagnostic_pool(
            chapters=chapters,
            user_prompt=user_prompt,
            digest_mode=digest_mode,
        )
        for item in fallback:
            key = _text(item.question).casefold()
            if key in seen:
                continue
            result.append(item)
            if len(result) >= 4:
                break
        return result[:4]
    return _fallback_diagnostic_pool(
        chapters=chapters,
        user_prompt=user_prompt,
        digest_mode=digest_mode,
    )


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
    explicit_topic = extract_explicit_learning_topic(resolved_user_prompt)
    display_course = (
        explicit_topic
        or _text(current.get("course_name") or previous.get("course_name"))
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


def _activity_point_for_requested_title(title: str, user_prompt: str) -> str:
    has_visual_request = bool(re.search(r"图示|示意|图像|配图|画图|图片", user_prompt))
    has_unit_test_request = bool(re.search(r"单元测试|测试|测验|小测", user_prompt))
    activity_items = [f"{title}核心概念", f"{title}方法与典型题型", f"{title}易错边界"]
    if has_visual_request:
        activity_items.insert(1, f"{title}图表读取方法")
    if has_unit_test_request:
        activity_items.append(f"{title}综合练习题型")
    return "、".join(activity_items)


def _align_chapters_to_requested_titles(
    chapters: list[PlannerChapterPlan],
    *,
    requested_titles: list[str],
    user_prompt: str,
) -> list[PlannerChapterPlan]:
    if not requested_titles:
        return chapters
    aligned: list[PlannerChapterPlan] = []
    for index, title in enumerate(requested_titles, start=1):
        seed_point = _activity_point_for_requested_title(title, user_prompt)
        if index <= len(chapters):
            chapter = chapters[index - 1]
            title_changed = _text(chapter.title) != title
            aligned.append(
                chapter.model_copy(
                    update={
                        "chapter_index": index,
                        "title": title,
                        "objective": seed_point if title_changed else chapter.objective,
                        "required_elements": _strings([seed_point, *chapter.required_elements])[:10],
                    }
                )
            )
            continue
        aligned.append(
            PlannerChapterPlan(
                chapter_index=index,
                title=title,
                objective=seed_point,
                required_elements=[seed_point],
                writing_instructions="围绕本章知识点生成清晰讲解。",
            )
        )
    return _reindex_chapters(aligned)


def _plan_text_for_requested_titles(requested_titles: list[str], *, user_prompt: str) -> str:
    path = " → ".join(f"《{title}》" for title in requested_titles)
    has_visual_request = bool(re.search(r"图示|示意|图像|配图|画图|图片", user_prompt))
    has_unit_test_request = bool(re.search(r"单元测试|测试|测验|小测", user_prompt))
    activity_items = ["讲解", "例题", "易错点", "练习"]
    if has_visual_request:
        activity_items.insert(0, "图表读取")
    if has_unit_test_request:
        activity_items.append("单元测试")
    activities = "、".join(activity_items)
    if len(requested_titles) == 2:
        return (
            f"课程按{path}两章推进。"
            f"第一章聚焦{requested_titles[0]}，先把概念边界和判断方法讲清；"
            f"第二章聚焦{requested_titles[1]}，把前一章的基础用到图像、方法和题目转换中。"
            f"每章正文内安排{activities}，让定义、方法、常见变式和检查点都落到对应章节。"
        )
    return (
        f"课程按{path}的顺序展开。"
        f"每个一级章节只负责自己的知识对象，正文内安排{activities}，"
        "把定义边界、方法步骤、常见变式和检查点落到对应章节。"
    )


def _normalize_chapter_count(
    chapters: list[PlannerChapterPlan],
    *,
    digest_mode: str,
    requested_chapter_count: int | None = None,
    requested_chapter_count_range: tuple[int, int] | None = None,
) -> list[PlannerChapterPlan]:
    if requested_chapter_count is not None:
        if len(chapters) > requested_chapter_count:
            return _cap_chapters_to_limit(
                chapters,
                chapter_limit=requested_chapter_count,
                note_prefix="相邻内容覆盖",
            )
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
    resolved_user_prompt = _text(_strip_diagnosis_metadata(user_prompt))
    current = _mapping(draft)
    previous = _mapping(latest_plan)
    current_constraints = _mapping(current.get("build_constraints"))
    mode = _normalize_digest_mode(requested_digest_mode or current.get("digest_mode") or previous.get("digest_mode"))
    requested_chapter_titles = extract_explicit_chapter_titles(resolved_user_prompt)
    explicit_topic = extract_explicit_learning_topic(resolved_user_prompt)
    display_course = (
        explicit_topic
        or _text(current.get("course_name") or previous.get("course_name"))
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
    chapters = _align_chapters_to_requested_titles(
        chapters,
        requested_titles=requested_chapter_titles,
        user_prompt=resolved_user_prompt,
    )
    chapters = _normalize_chapter_count(
        chapters,
        digest_mode=mode,
        requested_chapter_count=requested_chapter_count,
        requested_chapter_count_range=requested_chapter_count_range,
    )
    plan_text = _student_facing_text(current.get("plan") or previous.get("plan"))
    if requested_chapter_titles:
        plan_text = _plan_text_for_requested_titles(requested_chapter_titles, user_prompt=resolved_user_prompt)
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
