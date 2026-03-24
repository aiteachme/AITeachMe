"""Shared input models for unified digest builds."""

from __future__ import annotations

from pydantic import BaseModel, Field


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


class SharedInputs(BaseModel):
    """Outputs of the shared preparation layer."""

    source_packets: list[SourcePacket] = Field(default_factory=list)
    section_packets: list[SectionPacket] = Field(default_factory=list)
    chunk_identity_map: ChunkIdentityMap = Field(default_factory=ChunkIdentityMap)
    fast_hints: FastTopicHints = Field(default_factory=FastTopicHints)
    asset_registry: AssetRegistry = Field(default_factory=AssetRegistry)
