"""Central DocGen mode profiles.

This module keeps the small but important mapping between a DocGen mode and
its writing shape, budgets, thresholds, and prompt behavior in one place.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.workflows.digest.common.contracts import normalize_digest_mode

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
    max_writer_retries: int = 0

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
            return 950, 1300 if depth == "compact" else 1650

        base = 1850 if depth == "deep" else 1600
        return 1050, max(1400, base if chapter_count <= 8 else 1500)

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
        "开头用考点速览表列本章 2-5 个考点、重要程度、题型或任务场景和抓手",
        "二级标题用短考点名推进：概念、性质、方法、题型或操作任务",
        "每个考点先讲可直接用的方法、公式、步骤或判断口径",
        "方法后接例题、案例、代码/图表任务或小变式，并给解析、答案或判定依据",
        "图、表、公式和代码服务关键规则、题目条件或易错边界",
    ),
    course_flow_hints=(
        "考点速览表先定优先级，再按短考点逐个突破",
        "每个知识块先讲可执行的方法或判断口径，再用例题、任务和检查点落地",
        "相近题型、方法或条件变化用对照表或变式串起来",
    ),
    practice_focuses=(
        "高频题型或高频任务场景",
        "一题一解一错因的完整例题或案例",
        "图、表、代码、公式或条件的读题检查",
        "同一方法下的小变式和边界判断",
    ),
    content_mix_policy={
        "concept": 0.18,
        "procedure": 0.24,
        "principle": 0.06,
        "formula_model": 0.08,
        "skill": 0.30,
        "misconception": 0.12,
        "topic": 0.06,
        "application_case": 0.22,
    },
    example_density_policy={
        "minimum_practice_share": 0.45,
        "total_learning_activities_per_chapter": 8,
        "worked_examples_per_chapter": 3,
        "practice_tasks_per_chapter": 5,
        "training_chapter_min_examples": 8,
        "concept_chapter_min_examples": 3,
        "chapter_end_practice_min_tasks": 4,
        "chapter_end_practice_max_tasks": 6,
        "important_method_min_examples": 2,
        "quick_reference_per_chapter": 1,
        "policy_text": "紧凑节奏采用高密度练习安排：每章一张考点速览表，完整例题或任务约 3 个，短自测、变式或边界辨析约 4-6 个；题目形态由本章材料和章节角色决定。",
    },
    coverage_policy=(
        "优先覆盖本章材料中的高价值任务、关键方法和易错边界。",
        "每个重要方法至少安排一个贴合本章的例题、案例、反例或条件辨析；集中训练章节还要有变式和错因分析。",
        "例题、测验和练习集中在自然适合的章节或章末，题目形态贴合本章内容。",
        "收尾继续围绕本章具体对象、方法、任务或变式展开。",
        "非考试主题把例题表达为操作案例、任务场景、错误诊断和检查标准。",
    ),
    mode_writing_rule="紧凑节奏按考点速览、具体方法、例题任务、解析结论和错因边界组织，正文紧凑可检查。",
    prompt_label="紧凑节奏",
    prompt_priority="考点速览、具体方法、例题任务、解析结论和错因边界",
    prompt_opening_guidance="如果这是课程开篇，优先用直观场景、真实任务或学习动机破题，再建立概念直觉。",
    prompt_closing_guidance="如果这是最后一章，收束到本章关键任务、典型变式和易错边界。",
    prompt_research_focus="高价值主题、真实任务线索、典型例子和易错点",
    seed_target_length=950,
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
    prompt_extra_contract="正文采用考点讲义形态：考点速览表定优先级；每个考点讲清具体方法或判断口径，再接例题、任务、解析结论和错因边界。概念章用短例子和反例，方法章给步骤和检查点，训练章按真实题型或任务差异组织。",
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
        "章节收束时回到知识主线，并安排边界清楚的短练习、迁移例题或综合小结",
    ),
    practice_focuses=(
        "概念例题",
        "推理复述",
        "条件辨析",
        "迁移应用",
    ),
    content_mix_policy={
        "concept": 0.28,
        "procedure": 0.14,
        "principle": 0.18,
        "formula_model": 0.14,
        "skill": 0.12,
        "misconception": 0.08,
        "topic": 0.10,
        "application_case": 0.20,
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
        "章节复核时检查知识点是否有例题覆盖，并检查章末是否有短练习收束，不允许只有理论没有落地。",
    ),
    mode_writing_rule="系统节奏要突出定义、结构、推理、例子和迁移。",
    prompt_label="系统节奏",
    prompt_priority="定义、定理、推导、应用与章节之间的结构关系",
    prompt_opening_guidance="如果这是课程开篇，优先给出整体知识脉络。",
    prompt_closing_guidance="如果这是最后一章，回到本章核心结构和可迁移用法。",
    prompt_research_focus="定义、推导、适用条件、结构关系和可迁移例子",
    prompt_extra_contract="公式或定理要写清适用前提、推理过程和常见边界；章末用短练习、案例检查、边界辨析或迁移任务检查会不会用。",
    seed_target_length=1300,
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
    return "sprint" if normalize_digest_mode(digest_mode) == "sprint" else "systematic"


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
