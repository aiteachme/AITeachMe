"""章节蓝图与文档蓝图数据模型。

Phase 3 (Blueprint Planning) 和 Phase 5 (Pedagogical Audit) 的核心数据结构。

设计原则：
- ChapterArchetype 定义四种章节原型，每种有不同的教学目标
- ChapterBlueprint 包含 Learning Objectives（逆向设计核心）
- EvidenceBundle 为每章提供结构化证据（带溯源）
- ChapterAuditReport 检查教学目标达成度而非仅格式
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


# ── 章节原型 ────────────────────────────────────────────────────


class ChapterArchetype(str, Enum):
    """章节原型。每种原型有不同的教学目标和建议组件。"""

    CONCEPT_BUILD = "concept_build"    # 概念建立章
    METHOD_SOLVE = "method_solve"      # 方法求解章
    PROBLEM_TYPE = "problem_type"      # 题型突破章
    REVIEW_SPRINT = "review_sprint"    # 综合复习章

    @property
    def chinese_name(self) -> str:
        return {
            "concept_build": "概念建立",
            "method_solve": "方法求解",
            "problem_type": "题型突破",
            "review_sprint": "综合复习",
        }[self.value]

    @property
    def suggested_components_stem(self) -> list[str]:
        """理工科建议组件。"""
        return {
            "concept_build": ["definition", "formula", "intuition", "minimal_example", "try_it"],
            "method_solve": ["prerequisite", "steps", "decision_points", "variations", "try_it"],
            "problem_type": ["pattern_recognition", "framework", "examples_easy_to_hard", "common_mistakes"],
            "review_sprint": ["formula_cheat_sheet", "memory_hooks", "pitfalls", "self_test"],
        }[self.value]

    @property
    def suggested_components_humanities(self) -> list[str]:
        """文科建议组件。"""
        return {
            "concept_build": ["definition", "background", "key_quotes", "context", "try_it"],
            "method_solve": ["analysis_framework", "case_study", "comparison", "try_it"],
            "problem_type": ["question_types", "answer_template", "model_answers", "common_mistakes"],
            "review_sprint": ["key_points_table", "comparison_chart", "timeline", "self_test"],
        }[self.value]


# ── 证据项 ──────────────────────────────────────────────────────


class EvidenceItem(BaseModel):
    """单条证据，保留溯源信息。"""

    content: str = ""
    source_file: str = ""          # 文件名
    source_page: int | None = None  # 原始页码
    source_section: str = ""       # 来源章节标题
    section_uid: str = ""          # 来源 SectionPacket.digest_chunk_uid
    confidence: float = 1.0


class EvidenceBundle(BaseModel):
    """单章可消费的结构化证据集。

    不再传原始 source_content 给 Writer，
    而是传结构化的证据包，防止 LLM 抄写原文。
    """

    chapter_index: int = 0
    definitions: list[EvidenceItem] = Field(default_factory=list)
    formulas: list[EvidenceItem] = Field(default_factory=list)
    methods: list[EvidenceItem] = Field(default_factory=list)
    examples: list[EvidenceItem] = Field(default_factory=list)
    exercises: list[EvidenceItem] = Field(default_factory=list)
    warnings: list[EvidenceItem] = Field(default_factory=list)

    @property
    def total_items(self) -> int:
        return (len(self.definitions) + len(self.formulas) + len(self.methods)
                + len(self.examples) + len(self.exercises) + len(self.warnings))

    def to_prompt_string(self) -> str:
        """将证据包格式化为 prompt 可用的字符串。"""
        parts: list[str] = []

        if self.definitions:
            parts.append("### 核心定义")
            for item in self.definitions:
                ref = f"（来源：{item.source_file}"
                if item.source_page:
                    ref += f" p.{item.source_page}"
                ref += "）"
                parts.append(f"- {item.content} {ref}")

        if self.formulas:
            parts.append("\n### 核心公式")
            for item in self.formulas:
                ref = f"（来源：{item.source_file}"
                if item.source_page:
                    ref += f" p.{item.source_page}"
                ref += "）"
                parts.append(f"- {item.content} {ref}")

        if self.methods:
            parts.append("\n### 方法 / 步骤")
            for item in self.methods:
                parts.append(f"- {item.content}")

        if self.examples:
            parts.append("\n### 可用例题")
            for i, item in enumerate(self.examples, 1):
                ref = f"（来源：{item.source_file}"
                if item.source_section:
                    ref += f", {item.source_section}"
                ref += "）"
                parts.append(f"- 例{i}：{item.content[:120]}... {ref}")

        if self.warnings:
            parts.append("\n### 易错点 / 注意事项")
            for item in self.warnings:
                parts.append(f"- ⚠️ {item.content}")

        if self.exercises:
            parts.append("\n### 可用练习题")
            for i, item in enumerate(self.exercises, 1):
                parts.append(f"- 练习{i}：{item.content[:100]}...")

        return "\n".join(parts) if parts else "（本章暂无结构化证据）"


# ── 章节蓝图 ────────────────────────────────────────────────────


class ChapterBlueprint(BaseModel):
    """单章蓝图。

    Phase 3 Blueprint Planning 的核心产出。
    每章的 learning_objectives 是逆向设计的关键。
    """

    index: int = 0
    title: str = ""
    archetype: ChapterArchetype = ChapterArchetype.CONCEPT_BUILD

    # 逆向设计核心：学完这章，学生应该能做到什么
    learning_objectives: list[str] = Field(default_factory=list)

    prerequisite_chapters: list[int] = Field(default_factory=list)
    target_clusters: list[str] = Field(default_factory=list)
    importance_label: str = "★★"   # "★★★ 核心" / "★★ 重要" / "★ 拓展"
    suggested_components: list[str] = Field(default_factory=list)
    evidence_budget_tokens: int = 3000


class DocumentBlueprint(BaseModel):
    """整本文档的蓝图。

    Phase 3 Blueprint Planning 的顶层产出。
    """

    mode: str = "systematic"       # "sprint" | "systematic"
    subject: str = ""
    main_theme: str = ""           # 全书主线
    chapters: list[ChapterBlueprint] = Field(default_factory=list)
    total_estimated_tokens: int = 0
    quality_target: str = ""       # "讲义" | "速查手册"

    @property
    def chapter_count(self) -> int:
        return len(self.chapters)


# ── 审校报告 ────────────────────────────────────────────────────


class ChapterAuditReport(BaseModel):
    """单章教学质量审校报告。

    Phase 5 Pedagogical Audit 的产出。
    不只查格式，检查教学目标达成度。
    """

    chapter_index: int = 0
    passed: bool = True

    # 教学质量指标
    objectives_coverage: float = 1.0    # Learning Objectives 覆盖率 (0~1)
    archetype_goal_met: bool = True     # 章节原型目标是否达成
    prerequisite_satisfied: bool = True  # 前置依赖是否满足
    balance_score: float = 1.0          # 概念/方法/例题/练习平衡度 (0~1)
    formula_fidelity: float = 1.0       # 公式保真度 (0~1)

    # 结构完整性
    has_try_it_section: bool = False     # 是否有"尝试一下"练习块
    has_source_citations: bool = False   # 是否有溯源标注

    # 详情
    issues: list[str] = Field(default_factory=list)
    fix_actions: list[str] = Field(default_factory=list)

    @property
    def needs_repair(self) -> bool:
        return not self.passed or bool(self.fix_actions)


__all__ = [
    "ChapterArchetype",
    "ChapterAuditReport",
    "ChapterBlueprint",
    "DocumentBlueprint",
    "EvidenceBundle",
    "EvidenceItem",
]
