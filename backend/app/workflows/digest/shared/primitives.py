"""教学语义原语与材料画像数据模型。

Phase 0 (MaterialProfile, DigestModeDecision) 和
Phase 1 (ContentPrimitive, PedagogicalBlock) 的核心数据结构。

设计原则：
- ContentPrimitive 是最小教学原子，比 SectionPacket 粒度更细
- PedagogicalBlock 是若干 primitive 的可教学组合
- MaterialProfile 描述整批材料的统计画像
- DigestModeDecision 决定走 sprint 还是 systematic
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


# ── Phase 1: 教学语义原语 ──────────────────────────────────────


class PrimitiveType(str, Enum):
    """ContentPrimitive 的类型。"""

    DEFINITION = "definition"      # 定义 / 概念
    THEOREM = "theorem"            # 定理 / 引理 / 推论
    FORMULA = "formula"            # 独立公式块
    METHOD = "method"              # 方法 / 步骤 / 解法
    EXAMPLE = "example"            # 例题 / 示例（含解答）
    EXERCISE = "exercise"          # 习题 / 练习（无解答）
    WARNING = "warning"            # 易错点 / 注意事项
    NARRATIVE = "narrative"        # 叙述 / 背景 / 过渡
    COMPARISON = "comparison"      # 对比 / 区分
    HISTORICAL = "historical"      # 历史背景 / 人物事件
    NOISE = "noise"                # OCR 噪声 / 无用内容


class ContentPrimitive(BaseModel):
    """最小教学原子。

    一个 SectionPacket 可以包含多个 ContentPrimitive。
    例如一个 section 可能同时包含定义 + 公式 + 例题。
    """

    uid: str
    type: PrimitiveType = PrimitiveType.NARRATIVE
    content: str = ""
    source_file_id: int = 0
    source_filename: str = ""
    source_page: int | None = None
    section_uid: str = ""          # 来源 SectionPacket.digest_chunk_uid
    chunk_index: int = 0
    formulas: list[str] = Field(default_factory=list)
    confidence: float = 1.0        # 分类置信度
    classifier: str = "rule"       # "rule" | "llm"


class BlockRole(str, Enum):
    """PedagogicalBlock 在教学中的角色。"""

    CONCEPT = "concept"            # 概念讲解块
    METHOD = "method"              # 方法流程块
    PRACTICE = "practice"          # 练习 / 例题块
    MIXED = "mixed"                # 混合块


class PedagogicalBlock(BaseModel):
    """若干 ContentPrimitive 的可教学组合。

    相邻的 primitive 如果属于同一教学单元就合并为一个 block。
    例如: [definition + formula + example] → 一个 concept block。
    """

    uid: str
    topic_hint: str = ""           # 粗粒度主题名（聚类前的猜测）
    primitives: list[ContentPrimitive] = Field(default_factory=list)
    role: BlockRole = BlockRole.MIXED
    exam_frequency: str = "unknown"  # "high" | "medium" | "low" | "unknown"

    @property
    def primitive_types(self) -> set[str]:
        """返回本 block 包含的所有 primitive 类型。"""
        return {p.type.value for p in self.primitives}

    @property
    def has_example(self) -> bool:
        return any(p.type in (PrimitiveType.EXAMPLE, PrimitiveType.EXERCISE)
                   for p in self.primitives)

    @property
    def has_formula(self) -> bool:
        return any(p.type == PrimitiveType.FORMULA or p.formulas
                   for p in self.primitives)

    @property
    def total_chars(self) -> int:
        return sum(len(p.content) for p in self.primitives)


# ── Phase 0: 材料画像 ──────────────────────────────────────────


class MaterialStats(BaseModel):
    """材料集的统计指标（纯规则计算，0 API 调用）。"""

    total_sources: int = 0          # 上传文件数
    total_sections: int = 0         # section 总数
    total_chars: int = 0            # 总字符数
    formula_count: int = 0          # 公式数
    formula_density: float = 0.0    # 公式数 / section 数
    exercise_count: int = 0         # 习题数
    exercise_density: float = 0.0   # 习题数 / section 数
    image_count: int = 0            # 图片数
    table_count: int = 0            # 表格数
    ocr_noise_ratio: float = 0.0    # OCR 噪声比例（乱码 section/总 section）
    source_overlap: float = 0.0     # 跨文件重复度（0~1）


class MaterialProfile(BaseModel):
    """材料集的整体画像。

    综合了统计信息和学科识别结果。
    Phase 0 的核心输出之一。
    """

    subject: str = ""
    sub_subjects: list[str] = Field(default_factory=list)
    material_types: dict[str, int] = Field(default_factory=dict)
    stats: MaterialStats = Field(default_factory=MaterialStats)
    discipline: str = ""
    difficulty_level: str = ""


class DigestMode(str, Enum):
    """Digest 生成模式。"""

    SPRINT = "sprint"              # 速成课（冲刺讲义）
    SYSTEMATIC = "systematic"      # 系统课（完整讲义）


class DigestModeDecision(BaseModel):
    """Digest 模式决策。

    综合用户指定 / 学科元数据 / 材料自动识别三方面信息。
    Phase 0 的核心输出之一。
    """

    mode: DigestMode = DigestMode.SYSTEMATIC
    confidence: float = 0.8
    reason: str = ""
    user_override: bool = False    # 用户是否显式指定了模式
    evidence: dict[str, str] = Field(default_factory=dict)


# ── Phase 2: 主题聚类 ──────────────────────────────────────────


class TopicImportance(str, Enum):
    """主题重要度等级。"""

    CORE = "core"                  # ★★★ 核心
    IMPORTANT = "important"        # ★★ 重要
    SUPPLEMENTARY = "supplementary"  # ★ 拓展


class TopicCluster(BaseModel):
    """跨文件、跨章节归并后的主题簇。

    Phase 2 的核心输出。同时喂给文档规划和图谱构建。
    """

    canonical_name: str = ""
    aliases: list[str] = Field(default_factory=list)
    blocks: list[PedagogicalBlock] = Field(default_factory=list)
    importance: TopicImportance = TopicImportance.IMPORTANT
    community_id: str = ""         # Leiden 社区 ID（Phase 2b）
    formulas: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    example_count: int = 0
    primary_type: str = "mixed"    # concept_heavy / method_heavy / exercise_heavy

    @property
    def total_primitives(self) -> int:
        return sum(len(b.primitives) for b in self.blocks)


__all__ = [
    "BlockRole",
    "ContentPrimitive",
    "DigestMode",
    "DigestModeDecision",
    "MaterialProfile",
    "MaterialStats",
    "PedagogicalBlock",
    "PrimitiveType",
    "TopicCluster",
    "TopicImportance",
]
