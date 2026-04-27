"""Data contracts for knowledge-doc graph synchronization."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.workflows.digest.common.markdown_knowledge_anchors import MarkdownKnowledgeUnit


@dataclass(slots=True)
class KnowledgeSyncReport:
    """Summary of one incremental sync pass."""

    subject: str
    build_revision_no: int
    synced_unit_keys: list[str] = field(default_factory=list)
    knowledge_image_count: int = 0
    created_unit_ids: list[int] = field(default_factory=list)
    updated_unit_ids: list[int] = field(default_factory=list)
    deprecated_unit_ids: list[int] = field(default_factory=list)
    created_edge_ids: list[int] = field(default_factory=list)
    updated_edge_ids: list[int] = field(default_factory=list)
    deprecated_edge_ids: list[int] = field(default_factory=list)
    section_count: int = 0
    chapter_count: int = 0
    chapter_split_count: int = 0
    chapter_task_count: int = 0
    subsection_task_count: int = 0
    llm_section_count: int = 0
    markdown_short_circuit_section_count: int = 0
    llm_error_count: int = 0
    empty_llm_result_count: int = 0
    empty_repair_attempt_count: int = 0
    empty_repair_success_count: int = 0
    total_extracted_node_count: int = 0
    total_extracted_edge_count: int = 0
    elapsed_ms: int = 0
    sync_run_id: int | None = None
    doc_version_no: int = 0
    source_ref_count: int = 0
    backbone_unit_count: int = 0
    backbone_edge_count: int = 0
    stable_anchor_count: int = 0

    @property
    def unit_change_count(self) -> int:
        return len(self.created_unit_ids) + len(self.updated_unit_ids) + len(self.deprecated_unit_ids)

    @property
    def edge_change_count(self) -> int:
        return len(self.created_edge_ids) + len(self.updated_edge_ids) + len(self.deprecated_edge_ids)

    @property
    def deprecated_unit_count(self) -> int:
        return len(self.deprecated_unit_ids)

    @property
    def deprecated_edge_count(self) -> int:
        return len(self.deprecated_edge_ids)


@dataclass(slots=True)
class MarkdownExtractedEdge:
    """Chunk-level extracted edge resolved to markdown-sync anchors."""

    source_anchor: str
    target_anchor: str
    edge_type: str
    description: str
    source_kind: str = "llm_relation"
    knowledge_document_id: int | None = None
    chapter_index: int = 0
    source_file_ids: list[int] = field(default_factory=list)
    quote_text: str = ""


@dataclass(slots=True)
class PendingMarkdownExtractedEdge:
    """Chunk-level extracted edge before endpoint anchors are resolved."""

    source_candidate_id: str | None
    target_candidate_id: str | None
    source_name: str
    target_name: str
    edge_type: str
    description: str
    source_kind: str = "llm_relation"
    knowledge_document_id: int | None = None
    chapter_index: int = 0
    source_file_ids: list[int] = field(default_factory=list)
    quote_text: str = ""


@dataclass(slots=True)
class SectionExtractionContext:
    """Context retained after one section extraction for cross-section merging."""

    section_index: int
    title: str
    header_path: str
    body_markdown: str
    primary_anchor: str | None = None
    primary_name: str = ""
    primary_type: str = ""
    knowledge_document_id: int | None = None
    source_file_ids: list[int] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class ChapterSourceContext:
    """DocGen source metadata for one published chapter."""

    knowledge_document_id: int | None = None
    chapter_index: int = 0
    title: str = ""
    summary: str = ""
    source_file_ids: list[int] = field(default_factory=list)


@dataclass(slots=True)
class SectionExtractionPayload:
    """Normalized result for one extracted markdown section."""

    units: list[MarkdownKnowledgeUnit]
    pending_edges: list[PendingMarkdownExtractedEdge]
    candidate_id_to_anchor: dict[str, str]
    anchors_by_name: dict[str, list[str]]
    anchors_by_normalized_name: dict[str, list[str]]
    node_contexts_by_anchor: dict[str, dict[str, object]]
    section_context: SectionExtractionContext
    diagnostics: dict[str, int]


@dataclass(slots=True)
class KnowledgeSyncRunContext:
    """Persistent run context shared by kg_doc_sync graph nodes."""

    subject: str
    build_revision_no: int
    sync_run_id: int
    doc_version_no: int
    structured_context: dict[str, object] = field(default_factory=dict)
    started_at: float = 0.0


@dataclass(slots=True)
class KnowledgeSyncExtractionPayload:
    """Pure extraction output before database persistence."""

    units: list[MarkdownKnowledgeUnit]
    extracted_edges: list[MarkdownExtractedEdge]
    diagnostics_totals: dict[str, int]


__all__ = [
    "ChapterSourceContext",
    "KnowledgeSyncExtractionPayload",
    "KnowledgeSyncReport",
    "KnowledgeSyncRunContext",
    "MarkdownExtractedEdge",
    "PendingMarkdownExtractedEdge",
    "SectionExtractionContext",
    "SectionExtractionPayload",
]
