"""Models for unified digest coordination."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChapterPrior(BaseModel):
    """Top-down chapter prior shared from docgen lane to graph lane."""

    chapter_index: int
    title: str
    section_titles: list[str] = Field(default_factory=list)
    key_terms: list[str] = Field(default_factory=list)
    chunk_uids: list[str] = Field(default_factory=list)


class ChapterPriors(BaseModel):
    """Collection of chapter priors."""

    chapters: list[ChapterPrior] = Field(default_factory=list)


class TopicAnchor(BaseModel):
    """Bottom-up topic anchor shared from graph lane to docgen lane."""

    topic_name: str
    knowledge_unit_type: str = "concept"
    confidence: float = 1.0
    chunk_uids: list[str] = Field(default_factory=list)


class TopicAnchorSnapshot(BaseModel):
    """Snapshot of resolved graph anchors for docs coverage review."""

    anchors: list[TopicAnchor] = Field(default_factory=list)


class MaterializedSections(BaseModel):
    """Canonical chunk materialization persisted for one build session."""

    build_session_id: str
    source_file_ids: list[int] = Field(default_factory=list)
    document_ids: list[int] = Field(default_factory=list)
    chunk_ids: list[int] = Field(default_factory=list)
    chunk_uid_to_chunk_id: dict[str, int] = Field(default_factory=dict)
    chunk_id_to_chunk_uid: dict[int, str] = Field(default_factory=dict)
