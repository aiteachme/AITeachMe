"""Shared input models for digest builds."""

from __future__ import annotations

from enum import Enum

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class MaterialStats(BaseModel):
    """Material-level statistics computed without LLM calls."""

    total_sources: int = 0
    total_sections: int = 0
    total_chars: int = 0
    formula_count: int = 0
    formula_density: float = 0.0
    exercise_count: int = 0
    exercise_density: float = 0.0
    image_count: int = 0
    table_count: int = 0
    ocr_noise_ratio: float = 0.0
    source_overlap: float = 0.0


class MaterialProfile(BaseModel):
    """A compact profile for the current digest input set."""

    subject: str = ""
    sub_subjects: list[str] = Field(default_factory=list)
    material_types: dict[str, int] = Field(default_factory=dict)
    stats: MaterialStats = Field(default_factory=MaterialStats)
    discipline: str = ""
    difficulty_level: str = ""


class DigestMode(str, Enum):
    """Digest generation mode."""

    SPRINT = "sprint"
    SYSTEMATIC = "systematic"


class DigestModeDecision(BaseModel):
    """Mode decision shared by planner, docgen, and graph lanes."""

    mode: DigestMode = DigestMode.SYSTEMATIC
    confidence: float = 0.8
    reason: str = ""
    user_override: bool = False
    evidence: dict[str, str] = Field(default_factory=dict)


class SourcePacket(BaseModel):
    """A normalized source file payload prepared once per build."""

    file_id: int
    filename: str
    filetype: str
    markdown_path: str
    asset_dir: str
    normalized_content: str
    char_count: int
    has_formulas: bool
    has_tables: bool
    has_images: bool
    image_refs: list[str] = Field(default_factory=list)


class SectionPacket(BaseModel):
    """Canonical source unit shared by docs, graph, and curriculum."""

    digest_chunk_uid: str
    source_file_id: int
    source_filename: str
    chunk_index: int
    page_num: int | None = None
    title: str
    header_path: str
    level: int
    normalized_content: str
    preview: str
    char_count: int
    formula_refs: list[str] = Field(default_factory=list)
    question_block_count: int = 0
    header_candidates: list[str] = Field(default_factory=list)
    image_refs: list[str] = Field(default_factory=list)


class AssetItem(BaseModel):
    """One image-like asset extracted by ingest."""

    filename: str
    file_id: int
    page_number: int | None = None
    asset_type: str
    file_size: int
    ocr_available: bool = False


class AssetRegistry(BaseModel):
    """Registry of source assets available during docs generation."""

    subject: str = ""
    asset_dir: str = ""
    assets: list[AssetItem] = Field(default_factory=list)

    def get_assets_for_file(self, file_id: int) -> list[AssetItem]:
        """Return all assets for one file."""

        return [asset for asset in self.assets if asset.file_id == file_id]


class FastTopicHints(BaseModel):
    """Rule-based hints used to stabilize chapter planning and extraction."""

    high_freq_terms: list[tuple[str, int]] = Field(default_factory=list)
    chapter_candidates: list[str] = Field(default_factory=list)
    formula_patterns: list[str] = Field(default_factory=list)
    question_density: float = 0.0


class ChunkIdentityMap(BaseModel):
    """Stable section identity mapping for cross-lane bookkeeping."""

    chunk_uid_to_section: dict[str, int] = Field(default_factory=dict)
    section_to_chunk_uid: dict[int, str] = Field(default_factory=dict)


class MaterializedSections(BaseModel):
    """Canonical chunk materialization persisted for one digest lane run."""

    build_session_id: str
    source_file_ids: list[int] = Field(default_factory=list)
    document_ids: list[int] = Field(default_factory=list)
    chunk_ids: list[int] = Field(default_factory=list)
    chunk_uid_to_chunk_id: dict[str, int] = Field(default_factory=dict)
    chunk_id_to_chunk_uid: dict[int, str] = Field(default_factory=dict)


class TopicAnchor(BaseModel):
    """Knowledge-graph topic anchor produced during graph finalization."""

    topic_name: str
    node_type: str = "Topic"
    confidence: float = 1.0
    chunk_uids: list[str] = Field(default_factory=list)


class TopicAnchorSnapshot(BaseModel):
    """Snapshot of graph anchors used by graph status and diagnostics."""

    anchors: list[TopicAnchor] = Field(default_factory=list)


class SubjectProfile(BaseModel):
    """Detected discipline profile used to guide both lanes."""

    subject_slug: str = ""
    subject_name: str = ""
    subject_description: str = ""
    discipline: str = ""  # e.g. "数学", "物理", "计算机科学"
    sub_discipline: str = ""  # e.g. "线性代数", "量子力学"
    content_type: str = ""  # "textbook", "exam_paper", "lecture_notes", "mixed"
    difficulty_level: str = ""  # "introductory", "intermediate", "advanced"
    key_topics: list[str] = Field(default_factory=list)
    has_heavy_formulas: bool = False
    has_heavy_questions: bool = False
    has_heavy_diagrams: bool = False
    teaching_style_hint: str = ""  # guidance for writer prompt

    def build_context_string(self) -> str:
        """Build a concise context string for LLM prompts."""

        parts: list[str] = []
        if self.subject_name:
            parts.append(f"学科：{self.subject_name}")
        if self.discipline:
            label = self.discipline
            if self.sub_discipline:
                label += f" > {self.sub_discipline}"
            parts.append(f"领域：{label}")
        if self.subject_description:
            parts.append(f"描述：{self.subject_description[:120]}")
        if self.content_type:
            type_labels = {
                "textbook": "教材",
                "exam_paper": "试卷/考题",
                "lecture_notes": "讲义/笔记",
                "mixed": "混合材料",
            }
            parts.append(f"材料类型：{type_labels.get(self.content_type, self.content_type)}")
        if self.difficulty_level:
            level_labels = {
                "introductory": "入门级",
                "intermediate": "中级",
                "advanced": "高级/进阶",
            }
            parts.append(f"难度：{level_labels.get(self.difficulty_level, self.difficulty_level)}")
        if self.key_topics:
            parts.append(f"核心主题：{', '.join(self.key_topics[:8])}")
        return "\n".join(parts) if parts else "（未识别学科）"


class DigestMaterialContext(BaseModel):
    """Digest-wide material understanding package prepared once and reused by lanes.

    中文理解：这是 Digest 的“资料理解包”，统一打包文件正文、切片、主题提示、
    资产、学科画像、材料统计和模式判断，供 planner / docgen / KG 复用。
    """

    model_config = ConfigDict(populate_by_name=True)

    source_documents: list[SourcePacket] = Field(
        default_factory=list,
        validation_alias=AliasChoices("source_documents", "source_packets"),
    )
    material_sections: list[SectionPacket] = Field(
        default_factory=list,
        validation_alias=AliasChoices("material_sections", "section_packets"),
    )
    chunk_identity_map: ChunkIdentityMap = Field(default_factory=ChunkIdentityMap)
    material_hints: FastTopicHints = Field(
        default_factory=FastTopicHints,
        validation_alias=AliasChoices("material_hints", "fast_hints"),
    )
    material_assets: AssetRegistry = Field(
        default_factory=AssetRegistry,
        validation_alias=AliasChoices("material_assets", "asset_registry"),
    )
    learning_domain_profile: SubjectProfile = Field(
        default_factory=SubjectProfile,
        validation_alias=AliasChoices("learning_domain_profile", "subject_profile"),
    )
    material_stats_profile: MaterialProfile = Field(
        default_factory=MaterialProfile,
        validation_alias=AliasChoices("material_stats_profile", "material_profile"),
    )
    course_mode_decision: DigestModeDecision = Field(
        default_factory=DigestModeDecision,
        validation_alias=AliasChoices("course_mode_decision", "digest_mode_decision"),
    )
    material_digest: str = ""

    @property
    def source_packets(self) -> list[SourcePacket]:
        return self.source_documents

    @source_packets.setter
    def source_packets(self, value: list[SourcePacket]) -> None:
        self.source_documents = value

    @property
    def section_packets(self) -> list[SectionPacket]:
        return self.material_sections

    @section_packets.setter
    def section_packets(self, value: list[SectionPacket]) -> None:
        self.material_sections = value

    @property
    def fast_hints(self) -> FastTopicHints:
        return self.material_hints

    @fast_hints.setter
    def fast_hints(self, value: FastTopicHints) -> None:
        self.material_hints = value

    @property
    def asset_registry(self) -> AssetRegistry:
        return self.material_assets

    @asset_registry.setter
    def asset_registry(self, value: AssetRegistry) -> None:
        self.material_assets = value

    @property
    def subject_profile(self) -> SubjectProfile:
        return self.learning_domain_profile

    @subject_profile.setter
    def subject_profile(self, value: SubjectProfile) -> None:
        self.learning_domain_profile = value

    @property
    def material_profile(self) -> MaterialProfile:
        return self.material_stats_profile

    @material_profile.setter
    def material_profile(self, value: MaterialProfile) -> None:
        self.material_stats_profile = value

    @property
    def digest_mode_decision(self) -> DigestModeDecision:
        return self.course_mode_decision

    @digest_mode_decision.setter
    def digest_mode_decision(self, value: DigestModeDecision) -> None:
        self.course_mode_decision = value


# Backward-compatible alias kept for existing docgen / KG / tests during migration.
SharedInputs = DigestMaterialContext
