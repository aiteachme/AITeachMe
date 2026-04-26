"""Central DocGen mode profiles.

This module keeps the small but important mapping between a DocGen mode and
its writing shape, budgets, thresholds, and prompt behavior in one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DocGenMode = Literal["sprint", "systematic"]

BASE_WRITING_RULES: tuple[str, ...] = (
    "严格按用户确认的章节边界写作，不新增、删除或重排章节。",
    "优先使用本地学习资料；外部来源只用于补缺和校准。",
    "例题若非原始资料或可靠来源，不得称为真题，只能称为自测例题或变式练习。",
    "所有术语、公式和推理必须给出可读解释，避免只抛结论。",
)


@dataclass(frozen=True)
class DocGenModeProfile:
    mode: DocGenMode
    # These are writer/editor hints, not required headings. Keep them phrased
    # as teaching focuses so downstream prompts do not turn them into a rigid
    # chapter template.
    chapter_format: tuple[str, ...]
    course_flow_hints: tuple[str, ...]
    practice_focuses: tuple[str, ...]
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

    def word_budget(self, *, chapter_count: int, depth_level: str) -> tuple[int, int]:
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
        "优先点明本章最可能考什么、先拿什么分",
        "用高频考点表意识提炼重要程度、分值感和常见题型",
        "把核心概念压成最短可执行判断路径",
        "用题眼、解题模板和变式练习带出方法",
        "点出易错边界、不能硬套的条件和判定标准",
    ),
    course_flow_hints=(
        "课时开头先给考点/题型/分值感，再进入概念或公式",
        "每个方法尽量接一道短例题或小变式，直接暴露题眼",
        "讲完一组题型后，用例题解析、变式题和易错辨析收束",
    ),
    practice_focuses=(
        "速判例题",
        "题眼定位",
        "变式训练",
        "易错辨析",
    ),
    mode_writing_rule="冲刺模式要突出题型、速判、例题解析和易错辨析。",
    prompt_label="冲刺型",
    prompt_priority="抓重点、抓题型、抓易错点",
    prompt_opening_guidance="如果这是课程开篇，本章必须先用直观场景、常见题型或学习动机破题，再建立概念直觉。",
    prompt_closing_guidance="如果这是课程收束章，本章必须回收高频题型、易错点和综合例题解析。",
    prompt_research_focus="高频考点、题型线索、典型例题和易错点",
    seed_target_length=950,
    fallback_teaching_outline=("先标出高频考点和题型", "用典型题带出最短方法", "最后辨析易错边界"),
    gap_query_suffixes=("高频题型", "易错点", "典型例题"),
    practice_style="exam",
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
        "章节收束时回到知识主线，并安排迁移例题或综合小结",
    ),
    practice_focuses=(
        "概念例题",
        "推理复述",
        "条件辨析",
        "迁移应用",
    ),
    mode_writing_rule="系统模式要突出定义、结构、推理、例子和迁移。",
    prompt_label="系统型",
    prompt_priority="定义、定理、推导、应用与章节之间的结构关系",
    prompt_opening_guidance="如果这是课程开篇，本章必须给出整体知识脉络；不要自行输出任何资产占位符。",
    prompt_closing_guidance="如果这是课程收束章，本章必须回收全文主线，并给出进一步深入学习的建议。",
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
