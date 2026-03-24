"""Models for unified digest coordination."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChapterPrior(BaseModel):
    """Top-down chapter prior shared from docs lane to graph lane."""

    chapter_index: int
    title: str
    section_titles: list[str] = Field(default_factory=list)
    key_terms: list[str] = Field(default_factory=list)
    chunk_uids: list[str] = Field(default_factory=list)


class ChapterPriors(BaseModel):
    """Collection of chapter priors."""

    chapters: list[ChapterPrior] = Field(default_factory=list)


class TopicAnchor(BaseModel):
    """Bottom-up topic anchor shared from graph lane to docs lane."""

    topic_name: str
    node_type: str = "Topic"
    confidence: float = 1.0
    chunk_uids: list[str] = Field(default_factory=list)


class TopicAnchorSnapshot(BaseModel):
    """Snapshot of resolved graph anchors for docs coverage review."""

    anchors: list[TopicAnchor] = Field(default_factory=list)


class DocGap(BaseModel):
    """A docs topic that has no aligned graph coverage."""

    chapter_index: int
    chapter_title: str
    missing_terms: list[str] = Field(default_factory=list)
    severity: float = 0.0


class GraphGap(BaseModel):
    """A graph topic that is not covered by any chapter."""

    node_name: str
    node_type: str
    chunk_uids: list[str] = Field(default_factory=list)
    no_chapter_coverage: bool = False


class OrphanSignal(BaseModel):
    """A structural warning discovered during consistency checks."""

    chapter_index: int
    chapter_title: str
    orphan_type: str
    orphan_count: int


class TaxonomyDrift(BaseModel):
    """A naming drift between docs and graph for the same chunks."""

    chunk_uids: list[str] = Field(default_factory=list)
    doc_name: str
    graph_name: str
    semantic_distance: float = 0.0


class CoverageReport(BaseModel):
    """Consistency report across docs and graph outputs."""

    doc_over_graph_gaps: list[DocGap] = Field(default_factory=list)
    graph_over_doc_gaps: list[GraphGap] = Field(default_factory=list)
    orphan_signals: list[OrphanSignal] = Field(default_factory=list)
    taxonomy_drifts: list[TaxonomyDrift] = Field(default_factory=list)

    def has_gaps(self) -> bool:
        """Return whether any coverage issue exists."""

        return bool(
            self.doc_over_graph_gaps
            or self.graph_over_doc_gaps
            or self.orphan_signals
            or self.taxonomy_drifts
        )

    def gap_count(self) -> int:
        """Return the total number of reported issues."""

        return (
            len(self.doc_over_graph_gaps)
            + len(self.graph_over_doc_gaps)
            + len(self.orphan_signals)
            + len(self.taxonomy_drifts)
        )


class RepairBudget(BaseModel):
    """Bounded repair budget for consistency fixes."""

    max_chapter_rewrites: int = 2
    max_chunk_reextracts: int = 3
    max_llm_calls: int = 5


class RepairResult(BaseModel):
    """Repair actions chosen within the current budget."""

    repaired_chapters: list[int] = Field(default_factory=list)
    reextracted_chunks: list[str] = Field(default_factory=list)
    llm_calls_used: int = 0


class MaterializedSections(BaseModel):
    """Canonical chunk materialization persisted for one build session."""

    build_session_id: str
    source_file_ids: list[int] = Field(default_factory=list)
    document_ids: list[int] = Field(default_factory=list)
    chunk_ids: list[int] = Field(default_factory=list)
    chunk_uid_to_chunk_id: dict[str, int] = Field(default_factory=dict)
    chunk_id_to_chunk_uid: dict[int, str] = Field(default_factory=dict)
