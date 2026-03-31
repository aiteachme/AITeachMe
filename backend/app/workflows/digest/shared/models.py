"""Shared input models for unified digest builds."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.workflows.digest.shared.primitives import DigestModeDecision, MaterialProfile


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


class SharedInputs(BaseModel):
    """Outputs of the shared preparation layer."""

    source_packets: list[SourcePacket] = Field(default_factory=list)
    section_packets: list[SectionPacket] = Field(default_factory=list)
    chunk_identity_map: ChunkIdentityMap = Field(default_factory=ChunkIdentityMap)
    fast_hints: FastTopicHints = Field(default_factory=FastTopicHints)
    asset_registry: AssetRegistry = Field(default_factory=AssetRegistry)
    subject_profile: SubjectProfile = Field(default_factory=SubjectProfile)
    material_profile: MaterialProfile = Field(default_factory=MaterialProfile)
    digest_mode_decision: DigestModeDecision = Field(default_factory=DigestModeDecision)
