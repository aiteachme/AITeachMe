"""Central DocGen mode profiles.

This module keeps the small but important mapping between a DocGen mode and
its writing shape, budgets, thresholds, and prompt behavior in one place.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

DocGenMode = Literal["sprint", "systematic"]

BASE_WRITING_RULES: tuple[str, ...] = (
    "严格按用户确认的章节边界写作，不新增、删除或重排章节。",
    "优先使用本地学习资料；外部来源只用于补缺和校准。",
    "没有原始资料或可靠来源支撑的题目，不要称为真题。",
    "所有术语、公式和推理必须给出可读解释，避免只抛结论。",
)


def _parse_target_word_range(target_length: str | None) -> tuple[int, int] | None:
    text = str(target_length or "").strip().lower().replace(",", "")
    if not text:
        return None

    values: list[int] = []
    has_wan_unit = "w" in text or "万" in text
    for match in re.finditer(r"(\d+(?:\.\d+)?)(\s*(?:k|千|w|万))?", text):
        raw_value = float(match.group(1))
        unit = (match.group(2) or "").strip()
        if unit in {"k", "千"}:
            multiplier = 1000
        elif unit in {"w", "万"} or (has_wan_unit and raw_value < 100):
            multiplier = 10000
        else:
            multiplier = 1
        parsed = int(round(raw_value * multiplier))
        if parsed > 0:
            values.append(parsed)

    if not values:
        return None
    low = min(values)
    high = max(values)
    return low, max(low, high)


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


@dataclass(frozen=True)
class DocGenModeProfile:
    mode: DocGenMode
    # These are writer/editor hints, not required headings. Keep them phrased
    # as teaching focuses so downstream prompts do not turn them into a rigid
    # chapter template.
    chapter_format: tuple[str, ...]
    course_flow_hints: tuple[str, ...]
    practice_focuses: tuple[str, ...]
    content_mix_policy: dict[str, float]
    example_density_policy: dict[str, float | int | str]
    coverage_policy: tuple[str, ...]
    mode_writing_rule: str
    prompt_label: str
    prompt_priority: str
    prompt_opening_guidance: str
    prompt_closing_guidance: str
    prompt_research_focus: str
    seed_target_length: int
    fallback_teaching_outline: tuple[str, ...]
    gap_query_suffixes: tuple[str, ...]
    practice_style: str
    coverage_threshold: float
    evidence_support_threshold: float
    repetition_tolerance: float
    patch_tolerance: float
    max_research_rounds: int
    max_local_queries: int
    max_web_queries: int
    max_opened_urls: int
    max_context_chars: int
    query_cap: int
    queries_per_round: int
    coverage_target: float
    min_score_gain: float
    max_gap_queries_per_round: int
    strategy_context_chars: int
    prompt_extra_contract: str = ""
    max_writer_retries: int = 1

    @property
    def writing_rules(self) -> list[str]:
        return [*BASE_WRITING_RULES, self.mode_writing_rule]

    @property
    def is_sprint(self) -> bool:
        return self.mode == "sprint"

    def word_budget(
        self,
        *,
        chapter_count: int,
        depth_level: str,
        target_length: str | None = None,
        target_total_words: int | None = None,
    ) -> tuple[int, int]:
        chapter_total = max(1, int(chapter_count or 1))
        exact_total = _positive_int(target_total_words)
        if exact_total is not None:
            per_chapter = max(1, round(exact_total / chapter_total))
            return per_chapter, per_chapter

        parsed_range = _parse_target_word_range(target_length)
        if parsed_range is not None:
            min_total, target_total = parsed_range
            min_words = max(1, round(min_total / chapter_total))
            target_words = max(min_words, round(target_total / chapter_total))
            return min_words, target_words

        depth = str(depth_level or "").strip().lower()
        if self.is_sprint:
            return 520, 850 if depth == "compact" else 1050

        base = 1500 if depth == "deep" else 1250
        return 850, max(1100, base if chapter_count <= 8 else 1200)

    def budget_policy(self) -> dict[str, int]:
        return {
            "max_research_rounds": self.max_research_rounds,
            "max_local_queries": self.max_local_queries,
            "max_web_queries": self.max_web_queries,
            "max_opened_urls": self.max_opened_urls,
            "max_context_chars": self.max_context_chars,
            "max_writer_retries": self.max_writer_retries,
        }

    def research_strategy(self) -> dict[str, float | int]:
        return {
            "max_rounds": self.max_research_rounds,
            "queries_per_round": self.queries_per_round,
            "query_cap": self.query_cap,
            "coverage_target": self.coverage_target,
            "max_total_chars": self.strategy_context_chars,
            "min_score_gain": self.min_score_gain,
            "max_gap_queries_per_round": self.max_gap_queries_per_round,
        }


_SPRINT_PROFILE = DocGenModeProfile(
    mode="sprint",
    chapter_format=(
        "开头先给本章高价值主题、常见任务/题型和最短学习路径",
        "用速查表或判断表压缩核心公式、规则、适用条件和常见问法",
        "每个重要方法都按“题目或任务条件 -> 处理步骤 -> 例题解析 -> 变式/易错”落地，并用表格、callout 或小标题把信息块分开",
        "例题要写出题目/案例、解析步骤、答案或结论、易错点，不能只有提示",
        "章节末尾用考前速查、易错边界和自测任务收束",
    ),
    course_flow_hints=(
        "课时开头先给高价值主题、常见任务/题型和重要程度，再进入概念或方法",
        "每个方法尽量接一个短例题、案例或小变式，直接写清题目条件、步骤和边界，避免整段平铺",
        "讲完一组任务/题型后，用例题解析、变式训练、易错辨析和速查表收束",
    ),
    practice_focuses=(
        "快速抓手",
        "关键线索定位",
        "变式训练",
        "易错辨析",
    ),
    content_mix_policy={
        "core_knowledge": 0.22,
        "method_demo": 0.28,
        "explanation_support": 0.10,
        "principle_reasoning": 0.08,
        "practice_assessment": 0.26,
        "knowledge_organization": 0.06,
        "application_extension": 0.16,
    },
    example_density_policy={
        "minimum_practice_share": 0.55,
        "worked_examples_per_chapter": 5,
        "practice_tasks_per_chapter": 5,
        "important_method_min_examples": 2,
        "quick_reference_per_chapter": 1,
        "policy_text": "快速复习节奏必须高密度使用例题、案例、变式、自测或实践任务；理论只服务会做题、会操作、会判断、会避坑。考试、计算或刷题类章节必须有自然生成的常见题型整理，并配足带解析和易错点的例题区，优先让学生通过例子学会用法。",
    },
    coverage_policy=(
        "优先覆盖高频题型、常见任务、关键方法和易错陷阱。",
        "每个重要方法至少安排一个标准例题/案例和一个变式或错误诊断；计算、考试或刷题类章节要明显多给例子，不能只列规则。",
        "非考试主题把例题表达为操作案例、任务场景、错误诊断和检查标准。",
        "快速复习章节必须能让学生扫到本章常见考法或任务类型、适用条件、处理步骤和容易失误的地方。",
    ),
    mode_writing_rule="快速复习节奏要突出重点、题型或任务整理、典型例题解析和易错辨析。",
    prompt_label="快速复习",
    prompt_priority="重点、常见任务/题型、可执行步骤、易错点",
    prompt_opening_guidance="如果这是课程开篇，优先用直观场景、常见任务/题型或学习动机破题，再建立概念直觉。",
    prompt_closing_guidance="如果这是课程收束章，优先回收高价值主题、易错点和综合任务/例题解析。",
    prompt_research_focus="高价值主题、任务/题型线索、典型例子和易错点",
    seed_target_length=950,
    fallback_teaching_outline=("先标出高价值主题和常见任务/题型", "用典型例子带出最短方法", "最后辨析易错边界"),
    gap_query_suffixes=("常见任务", "易错点", "典型例子"),
    practice_style="task_driven",
    coverage_threshold=0.6,
    evidence_support_threshold=0.48,
    repetition_tolerance=0.45,
    patch_tolerance=0.45,
    max_research_rounds=2,
    max_local_queries=3,
    max_web_queries=2,
    max_opened_urls=3,
    max_context_chars=4200,
    query_cap=4,
    queries_per_round=2,
    coverage_target=0.68,
    min_score_gain=0.08,
    max_gap_queries_per_round=2,
    strategy_context_chars=4200,
    prompt_extra_contract="快速复习章节必须显式形成“题型或任务整理 -> 条件与方法速查 -> 例题解析 -> 变式/易错 -> 自测”的学习闭环；标题必须按本章内容自然命名，不能由固定短语硬拼，但这些学习功能不能缺位。",
)

_SYSTEMATIC_PROFILE = DocGenModeProfile(
    mode="systematic",
    chapter_format=(
        "先建立本章在整门课里的位置和前后依赖",
        "把学习目标转成几个可理解的问题",
        "讲清关键概念、定义、性质、公式和适用前提",
        "展开方法、结构、推理路径和必要的证明直觉",
        "用例子、例题或迁移场景把抽象知识落地",
        "说明易错点、边界条件、反例和跨章联系",
    ),
    course_flow_hints=(
        "课时开头先给知识地图或问题动机，再展开定义与性质",
        "概念、公式或定理后接一个能体现条件的小例子",
        "章节收束时回到知识主线，并安排边界清楚的迁移例题或综合小结",
    ),
    practice_focuses=(
        "概念例题",
        "推理复述",
        "条件辨析",
        "迁移应用",
    ),
    content_mix_policy={
        "core_knowledge": 0.30,
        "method_demo": 0.16,
        "explanation_support": 0.14,
        "principle_reasoning": 0.18,
        "practice_assessment": 0.14,
        "knowledge_organization": 0.10,
        "application_extension": 0.10,
    },
    example_density_policy={
        "minimum_practice_share": 0.3,
        "worked_examples_per_chapter": 3,
        "practice_tasks_per_chapter": 3,
        "important_method_min_examples": 2,
        "policy_text": "系统课必须细讲核心知识，同时每个核心知识点都要有例题、案例、操作示例或练习任务支撑。",
    },
    coverage_policy=(
        "每个核心知识点至少被一个例题、案例、操作示例或练习任务覆盖。",
        "重要、易错或核心方法至少安排两个不同角度的例题或任务。",
        "章节复核时检查知识点是否有例题覆盖，不允许只有理论没有落地。",
    ),
    mode_writing_rule="系统课模式要突出定义、结构、推理、例子和迁移。",
    prompt_label="系统课",
    prompt_priority="定义、定理、推导、应用与章节之间的结构关系",
    prompt_opening_guidance="如果这是课程开篇，优先给出整体知识脉络。",
    prompt_closing_guidance="如果这是课程收束章，优先回收全文主线，并给出进一步深入学习的建议。",
    prompt_research_focus="定义、推导、适用条件、结构关系和可迁移例子",
    prompt_extra_contract="如果涉及公式或定理，不能只写结论，必须解释适用前提、推理过程和常见边界。",
    seed_target_length=1300,
    fallback_teaching_outline=("先讲清知识地图和定义", "再讲结构、条件与推理", "最后用例子和迁移收口"),
    gap_query_suffixes=("定义", "推导", "联系", "典型例子"),
    practice_style="reasoning",
    coverage_threshold=0.72,
    evidence_support_threshold=0.56,
    repetition_tolerance=0.3,
    patch_tolerance=0.32,
    max_research_rounds=3,
    max_local_queries=3,
    max_web_queries=4,
    max_opened_urls=5,
    max_context_chars=6200,
    query_cap=6,
    queries_per_round=3,
    coverage_target=0.82,
    min_score_gain=0.05,
    max_gap_queries_per_round=3,
    strategy_context_chars=6000,
)

_PROFILES: dict[DocGenMode, DocGenModeProfile] = {
    "sprint": _SPRINT_PROFILE,
    "systematic": _SYSTEMATIC_PROFILE,
}


def normalize_docgen_mode(digest_mode: str | None) -> DocGenMode:
    return "sprint" if str(digest_mode or "").strip().lower() == "sprint" else "systematic"


def get_docgen_mode_profile(digest_mode: str | None) -> DocGenModeProfile:
    return _PROFILES[normalize_docgen_mode(digest_mode)]


def is_sprint_docgen_mode(digest_mode: str | None) -> bool:
    return normalize_docgen_mode(digest_mode) == "sprint"


__all__ = [
    "BASE_WRITING_RULES",
    "DocGenMode",
    "DocGenModeProfile",
    "get_docgen_mode_profile",
    "is_sprint_docgen_mode",
    "normalize_docgen_mode",
]
