"""Knowledge-domain API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import PageParams


class DocGenBuildRequest(BaseModel):
    """Trigger knowledge-doc generation."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "file_uids": ["file_xxx", "file_yyy"],
                "prompt": "Generate review-oriented notes",
                "embedding_resolution": "rebuild",
                "build_type": "docs",
            }
        }
    )

    file_uids: list[str] | None = Field(
        default=None,
        description=(
            "Optional parsed raw file UIDs; omitted means auto-pick all available ready files for "
            "the subject. Ignored when `confirmed_plan_id` is provided."
        ),
    )
    prompt: str | None = Field(
        default=None,
        description=(
            "Optional user instruction for doc generation. Ignored when `confirmed_plan_id` is "
            "provided and the confirmed plan already freezes the build goal."
        ),
    )
    embedding_resolution: Literal["rebuild", "disable"] | None = Field(
        default=None,
        description="Optional subject-level embedding resolution chosen after a precheck conflict.",
    )
    build_type: Literal["docs"] = Field(
        default="docs",
        description=(
            "Build type. Public builds generate knowledge docs and may sync the graph according to settings."
        ),
    )
    confirmed_plan_id: str | None = Field(
        default=None,
        description=(
            "Planner-generated and confirmed build plan ID. `docs` builds require this field; "
            "when provided, the build uses the frozen file selection, chapter plan, and User prompt."
        ),
    )

class KnowledgeUnitsQueryRequest(PageParams):
    """Paginated KnowledgeUnit query."""

    knowledge_unit_type: str | None = Field(default=None, description="Optional KnowledgeUnit type filter.")


class KnowledgeUnitDetailRequest(BaseModel):
    """KnowledgeUnit detail query."""

    knowledge_unit_id: int = Field(description="KnowledgeUnit ID.")

    @model_validator(mode="after")
    def _normalize_knowledge_unit_id(self) -> "KnowledgeUnitDetailRequest":
        self.knowledge_unit_id = int(self.knowledge_unit_id)
        return self


class KnowledgeUnitRelationsRequest(BaseModel):
    """KnowledgeUnit relation query."""

    knowledge_unit_id: int = Field(description="KnowledgeUnit ID.")
    direction: Literal["both", "incoming", "outgoing"] = Field(default="both")
    edge_type: str | None = Field(default=None, description="Optional relation type filter.")


class KnowledgeUnitPathRequest(BaseModel):
    """KnowledgeUnit path query."""

    source_knowledge_unit_id: int = Field(description="Path start KnowledgeUnit ID.")
    target_knowledge_unit_id: int = Field(description="Path target KnowledgeUnit ID.")
    edge_type: str | None = Field(default=None, description="Optional relation type filter.")
    max_depth: int = Field(default=4, ge=1, le=8)


class KnowledgeSubgraphRequest(BaseModel):
    """Focus subgraph query."""

    center_knowledge_unit_id: int | None = Field(default=None, description="Optional center KnowledgeUnit ID.")
    topic: str | None = Field(default=None, description="Optional topic/name text filter.")
    edge_type: str | None = Field(default=None, description="Optional relation type filter.")
    hops: int = Field(default=1, ge=0, le=3)
    limit: int = Field(default=80, ge=1, le=300)


class KnowledgeRelationExplanationRequest(BaseModel):
    """Explain a relation path with evidence snippets."""

    source_knowledge_unit_id: int
    target_knowledge_unit_id: int
    edge_type: str | None = None
    max_depth: int = Field(default=3, ge=1, le=6)


class KnowledgeOverviewRequest(BaseModel):
    """Aggregated knowledge overview query."""

    include: list[str] | None = Field(
        default=None,
        description="Optional sections to include. Omit for default full payload.",
    )
    full: bool = Field(
        default=True,
        description="Whether to return full payload. Current implementation favors full payload.",
    )


class ChunkContextRequest(BaseModel):
    """Chat chunk context query."""

    chunk_id: int = Field(description="Document chunk ID.")


class KnowledgeBuildPrecheckConflictData(BaseModel):
    """Structured payload for one build-precheck conflict."""

    reason: str = Field(description="Stable reason code for the precheck conflict.")
    subject_model: str | None = Field(default=None, description="Subject-bound embedding model, if any.")
    subject_dim: int | None = Field(default=None, description="Subject-bound embedding dimension, if any.")
    runtime_model: str | None = Field(default=None, description="Current runtime embedding model, if any.")
    runtime_dim: int | None = Field(default=None, description="Current runtime embedding dimension, if any.")
    requires_full_rebuild: bool = Field(
        default=False,
        description="Whether restoring vector mode requires a full rebuild.",
    )
    vector_enabled_after_continue: bool = Field(
        default=False,
        description="Whether vector mode stays enabled after continuing without rebuild.",
    )


class SubjectVectorStatusResponse(BaseModel):
    """Subject-level vector capability status shown to the UI."""

    mode: str = Field(default="enabled", description="enabled / disabled")
    notice: str | None = Field(default=None, description="User-facing vector capability notice.")
    embedding_model: str | None = Field(default=None, description="Current subject-bound embedding model, if any.")
    vector_table: str | None = Field(default=None, description="Current subject-scoped vector index reference, if any.")


class DocGenBuildData(BaseModel):
    """Knowledge docs build response data."""

    accepted_file_uids: list[str] = Field(default_factory=list, description="Accepted ready raw file UIDs.")
    prompt: str | None = Field(
        default=None,
        description="Effective user prompt for the docs build after planner overrides are applied.",
    )
    ready_file_count: int = Field(default=0, description="Current ready file count for this subject.")
    requested_at: datetime = Field(description="Build request timestamp.")
    vector_status: SubjectVectorStatusResponse = Field(
        default_factory=SubjectVectorStatusResponse,
        description="Current subject-level vector capability status.",
    )
    planner_session_id: str | None = Field(default=None, description="Planner session id bound to this build.")
    confirmed_plan_id: str | None = Field(default=None, description="Confirmed build plan id bound to this build.")
    digest_mode: str | None = Field(default=None, description="Digest mode frozen in the confirmed build plan.")


class DocGenBuildCancelData(BaseModel):
    """Result of cancelling the active knowledge build."""

    subject: str
    status: str = "cancelled"
    cancelled_task_count: int = 0
    requested_at: datetime | None = None
    message: str = "已终止当前知识构建。"


class KnowledgeGraphBuildData(BaseModel):
    """Knowledge graph rebuild response data."""

    subject: str = Field(description="Subject slug.")
    status: str = Field(default="accepted", description="accepted / running")
    requested_at: datetime = Field(description="Graph build request timestamp.")
    build_group_id: str | None = Field(default=None, description="Runtime build group id.")
    build_session_id: str | None = Field(default=None, description="Graph sync session id.")
    source_file_ids: list[int] = Field(default_factory=list, description="Persisted source raw file ids from the docs manifest.")
    message: str = Field(default="已开始重建知识图谱。", description="User-facing response message.")


class BuildSampleCardResponse(BaseModel):
    """Lightweight preview card shown while digest is building."""

    title: str
    card_type: str = Field(description="mode / topic / concept / method")
    summary: str


class BuildPreviewNodeResponse(BaseModel):
    """One lightweight node preview surfaced during digest polling."""

    name: str
    knowledge_unit_type: str = Field(description="Standard KnowledgeUnit type")


class BuildPreviewChapterProgressResponse(BaseModel):
    """Per-chapter runtime progress shown while docgen is building."""

    chapter_index: int
    title: str
    status: str = Field(description="planned / researching / researched / drafting / drafted / completed")
    source_count: int = 0
    local_hits: int = 0
    web_hits: int = 0
    query_count: int = 0
    word_count: int = 0
    fallback_used: bool = False


class BuildPreviewRecentEventResponse(BaseModel):
    """Recent build events surfaced in the docs waiting UI."""

    stage: str
    chapter_index: int | None = None
    title: str | None = None
    summary: str
    created_at: datetime | None = None
    domains: list[str] = Field(default_factory=list, description="Top domains touched by this event, when applicable.")
    source_titles: list[str] = Field(default_factory=list, description="Short source titles surfaced for this event.")
    source_urls: list[str] = Field(default_factory=list, description="Representative URLs surfaced for this event.")


class BuildPreviewChapterPreviewResponse(BaseModel):
    """Per-chapter live preview surfaced while docgen is progressing."""

    chapter_index: int
    title: str
    status: str = Field(description="planned / generating / generated / enhancing / enhanced / reviewing / reviewed / completed")
    excerpt: str = Field(default="", description="Latest readable excerpt for the chapter preview.")
    latest_headings: list[str] = Field(default_factory=list, description="Recent section headings extracted from the chapter preview.")
    word_count: int = 0
    source_count: int = 0
    updated_at: datetime | None = Field(default=None, description="When this chapter preview was last refreshed.")


class BuildPreviewMergePreviewResponse(BaseModel):
    """Whole-document live preview surfaced before final publish."""

    latest_chapter_titles: list[str] = Field(default_factory=list, description="Latest resolved chapter titles in the merged preview.")
    draft_excerpt: str = Field(default="", description="Short excerpt from the current merged preview.")
    updated_at: datetime | None = Field(default=None, description="When the merged preview was last refreshed.")


class KnowledgeBuildPreviewResponse(BaseModel):
    """Human-facing preview payload for ongoing digest builds."""

    current_stage_description: str | None = Field(default=None, description="Friendly description of the current build stage.")
    digest_mode: str | None = Field(default=None, description="sprint / systematic")
    mode_reason: str | None = Field(default=None, description="Why the current digest mode was selected.")
    processed_chunks: int = Field(default=0, description="How many section chunks have been processed so far.")
    total_chunks: int = Field(default=0, description="Total number of section chunks for this build.")
    doc_sync_section_count: int = Field(default=0, description="How many knowledge-doc sections were analyzed during docs-sync.")
    doc_sync_llm_section_count: int = Field(default=0, description="How many docs-sync sections attempted structured LLM extraction.")
    discovered_node_count: int = Field(default=0, description="Current discovered knowledge-node count.")
    discovered_node_types: dict[str, int] = Field(default_factory=dict, description="Node counts by node type.")
    sample_nodes: list[BuildPreviewNodeResponse] = Field(default_factory=list, description="Sample discovered nodes.")
    sample_cards: list[BuildSampleCardResponse] = Field(default_factory=list, description="Small preview cards for the waiting UI.")
    plan_summary: str | None = Field(default=None, description="Confirmed build plan summary for the current build.")
    chapter_progress: list[BuildPreviewChapterProgressResponse] = Field(default_factory=list, description="Per-chapter progress for the current build.")
    recent_events: list[BuildPreviewRecentEventResponse] = Field(default_factory=list, description="Recent research / writing / publishing events for this build.")
    chapter_previews: list[BuildPreviewChapterPreviewResponse] = Field(default_factory=list, description="Readable per-chapter live previews for the build workspace.")
    merge_preview: BuildPreviewMergePreviewResponse | None = Field(default=None, description="Merged whole-document preview before final publish.")
    latest_chapter_titles: list[str] = Field(default_factory=list, description="Recently staged or published chapter titles.")
    draft_excerpt: str = Field(default="", description="Short excerpt from the current draft markdown, if any.")


class KnowledgeBuildMetricsResponse(BaseModel):
    """Compact build diagnostics used by polling UIs."""

    llm_total_calls: int = Field(default=0, description="Total LLM calls recorded for the current build session.")
    failed_llm_call_count: int = Field(default=0, description="Failed LLM call count for the current build session.")
    llm_avg_latency_ms: float = Field(default=0.0, description="Average LLM latency in milliseconds.")
    call_count_by_lane: dict[str, int] = Field(default_factory=dict, description="LLM call count grouped by workflow lane.")


class KnowledgeGraphBuildMetricsResponse(BaseModel):
    """Stable graph-build metrics used by docs and graph progress UIs."""

    processed_chunks: int = Field(default=0, description="Legacy parsed-file chunk count; docs-sync builds keep this at 0.")
    doc_sync_section_count: int = Field(default=0, description="Knowledge-doc sections analyzed by kg_doc_sync.")
    doc_sync_unit_changes: int = Field(default=0, description="Knowledge units created or updated by docs-sync.")
    doc_sync_edge_changes: int = Field(default=0, description="Graph edges created or updated by docs-sync.")
    elapsed_ms: int = Field(default=0, description="Elapsed milliseconds for the latest graph-sync step.")
    revision_no: int = Field(default=0, description="Knowledge graph revision number produced by the latest docs-sync.")
    last_synced_doc_version_no: int = Field(default=0, description="Knowledge document version number last synced into the graph.")
    knowledge_doc_source: str | None = Field(default=None, description="Source of the knowledge document markdown used for docs-sync.")
    knowledge_doc_chapter_count: int = Field(default=0, description="Knowledge document chapter count seen by docs-sync.")
    source_ref_count: int = Field(default=0, description="Structured provenance refs written by the latest graph sync.")
    backbone_unit_count: int = Field(default=0, description="Knowledge units seeded from DocGen document_backbone.")
    backbone_edge_count: int = Field(default=0, description="Knowledge edges seeded from DocGen document_backbone.")
    stable_anchor_count: int = Field(default=0, description="Stable graph anchors seen during the latest docs-sync.")
    deprecated_unit_count: int = Field(default=0, description="Knowledge units deprecated by the latest docs-sync.")
    deprecated_edge_count: int = Field(default=0, description="Knowledge edges deprecated by the latest docs-sync.")
    prefetch_status: str | None = Field(default=None, description="DocGen-side KG prefetch status for the latest auto sync.")
    prefetch_section_count: int = Field(default=0, description="Section payloads produced by the DocGen-side KG prefetch.")
    prefetch_reused_section_count: int = Field(default=0, description="Prefetched section payloads reused by final graph sync.")
    prefetch_catchup_section_count: int = Field(default=0, description="Final sections that required normal catch-up extraction.")
    prefetch_stale_section_count: int = Field(default=0, description="Prefetched section payloads discarded because final content changed.")
    prefetch_failed_section_count: int = Field(default=0, description="Prefetch section payloads that failed before final graph sync.")


class KnowledgeBuildStatusResponse(BaseModel):
    """Minimal runtime metadata exposed to clients for docs polling."""

    status: str = Field(description="idle / accepted / running / publishing / completed / failed / cancelled")
    requested_at: datetime = Field(description="Build request timestamp.")
    stage: str = Field(description="Current lifecycle stage for the build.")
    error_message: str | None = Field(default=None, description="Build failure or cancellation reason.")
    draft_available: bool = Field(default=False, description="Whether a staging draft is currently available.")
    progress_pct: int = Field(default=0, description="Persisted backend progress percentage for the current build.")
    planner_session_id: str | None = Field(default=None, description="Planner session id bound to the current build.")
    confirmed_plan_id: str | None = Field(default=None, description="Confirmed build plan id bound to the current build.")
    digest_mode: str | None = Field(default=None, description="Digest mode for the current build.")
    mode_reason: str | None = Field(default=None, description="Reason for the current digest mode.")
    current_stage_description: str | None = Field(default=None, description="Friendly description of the current build stage.")


class KnowledgeBuildLaneRuntimeResponse(BaseModel):
    """One runtime lane snapshot used by polling clients."""

    lane: Literal["aggregate", "docgen", "graph"]
    build_group_id: str | None = Field(default=None, description="Shared build-group identifier across related lanes.")
    status: str = Field(description="idle / accepted / running / completed / failed / cancelled / skipped / partial_failed")
    stage: str = Field(description="Current lifecycle stage for this lane.")
    started_at: datetime | None = Field(default=None, description="Lane start timestamp.")
    finished_at: datetime | None = Field(default=None, description="Lane finish timestamp when terminal.")
    requested_at: datetime | None = Field(default=None, description="Original request timestamp for this lane.")
    error_message: str | None = Field(default=None, description="Lane failure or cancellation reason.")
    progress_pct: int = Field(default=0, description="Backend progress percentage for this lane.")
    current_stage_description: str | None = Field(default=None, description="Friendly description of the current lane stage.")
    metrics: dict[str, object] = Field(default_factory=dict, description="Compact metrics for this lane.")


class KnowledgeBuildRuntimeResponse(BaseModel):
    """Unified runtime response for aggregate/docgen/graph lanes."""

    build_group_id: str | None = Field(default=None, description="Shared build-group identifier across related lanes.")
    aggregate: KnowledgeBuildLaneRuntimeResponse | None = Field(default=None, description="Aggregate runtime across all required lanes.")
    docgen: KnowledgeBuildLaneRuntimeResponse | None = Field(default=None, description="DocGen lane runtime.")
    graph: KnowledgeBuildLaneRuntimeResponse | None = Field(default=None, description="Graph lane runtime.")
    docgen_preview: KnowledgeBuildPreviewResponse | None = Field(default=None, description="DocGen-oriented preview payload for waiting UIs.")
    docgen_metrics: KnowledgeBuildMetricsResponse | None = Field(default=None, description="DocGen-oriented live diagnostics for waiting UIs.")
    graph_metrics: KnowledgeGraphBuildMetricsResponse = Field(default_factory=KnowledgeGraphBuildMetricsResponse, description="Stable graph-build metrics for progress UIs.")


class DocGenGetResponse(BaseModel):
    """Knowledge docs get response."""

    exists: bool = Field(description="Whether a merged knowledge document exists.")
    markdown: str = Field(default="", description="Merged markdown content.")
    updated_at: datetime | None = Field(default=None, description="Last updated time of the merged markdown.")
    source_file_uids: list[str] = Field(default_factory=list, description="Source raw file UIDs used by the published docs.")
    prompt: str | None = Field(default=None, description="User prompt used for the published docs.")
    draft_markdown: str = Field(default="", description="Current staging draft markdown content, if available.")
    draft_updated_at: datetime | None = Field(default=None, description="Last updated time of the staging draft.")
    build: KnowledgeBuildStatusResponse | None = Field(default=None, description="Current or most recent build metadata.")
    build_preview: KnowledgeBuildPreviewResponse | None = Field(
        default=None,
        description="Lightweight preview payload for the ongoing build, surfaced through the docs polling endpoint.",
    )
    build_metrics: KnowledgeBuildMetricsResponse | None = Field(
        default=None,
        description="Compact live build diagnostics surfaced through the docs polling endpoint.",
    )
    vector_status: SubjectVectorStatusResponse = Field(
        default_factory=SubjectVectorStatusResponse,
        description="Current subject-level vector capability status.",
    )
    planner_session_id: str | None = Field(default=None, description="Planner session id bound to this build.")
    confirmed_plan_id: str | None = Field(default=None, description="Confirmed build plan id bound to this build.")
    digest_mode: str | None = Field(default=None, description="Digest mode frozen in the confirmed build plan.")


class KnowledgeUnitResponse(BaseModel):
    """KnowledgeUnit list item."""

    id: int
    subject: str
    knowledge_unit_type: str
    canonical_name: str
    status: str
    confidence: float
    type_confidence: float = 1.0
    type_source: str = "llm"
    created_at: datetime
    updated_at: datetime


class EvidenceSummary(BaseModel):
    """Evidence summary used in node detail."""

    id: int
    document_id: int
    chunk_id: int
    quote_text: str
    evidence_role: str
    field_scope: str
    confidence: float


class ChunkContextResponse(BaseModel):
    """Chat chunk context response."""

    chunk_id: int
    document_id: int
    document_title: str
    chunk_title: str
    chunk_header_path: str
    chunk_content: str


class AliasItem(BaseModel):
    """Node alias item."""

    id: int
    alias: str
    language: str
    source: str
    confidence: float
    is_primary: bool


class IncidentEdgeItem(BaseModel):
    """Incident edge item."""

    id: int
    edge_type: str
    direction: str = Field(description="outgoing or incoming.")
    other_node_id: int
    other_node_name: str
    other_node_type: str
    confidence: float


class KnowledgeGraphSourceRefResponse(BaseModel):
    """Structured source reference for a graph unit or edge."""

    id: int
    entity_type: str
    entity_id: int
    sync_run_id: int | None = None
    knowledge_document_id: int | None = None
    chapter_index: int = 0
    chapter_title: str | None = None
    doc_version_no: int = 0
    graph_revision_no: int = 0
    source_kind: str = ""
    anchor: str = ""
    source_file_ids: list[int] = Field(default_factory=list)
    quote_text: str = ""
    confidence: float = 1.0
    created_at: datetime


class NodeRevisionItem(BaseModel):
    """Current revision content for a knowledge node."""

    title: str
    summary: str
    body: str


class KnowledgeUnitDetailResponse(BaseModel):
    """KnowledgeUnit detail response."""

    id: int
    subject: str
    knowledge_unit_type: str
    canonical_name: str
    normalized_name: str
    status: str
    confidence: float
    type_confidence: float = 1.0
    type_source: str = "llm"
    current_revision: NodeRevisionItem | None = None
    aliases: list[AliasItem] = Field(default_factory=list)
    evidence: list[EvidenceSummary] = Field(default_factory=list)
    source_refs: list[KnowledgeGraphSourceRefResponse] = Field(default_factory=list)
    incident_edges: list[IncidentEdgeItem] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class GraphEdgeResponse(BaseModel):
    """Graph edge item used by full-graph query."""

    id: int
    source_node_id: int
    target_node_id: int
    edge_type: str
    weight: float
    confidence: float


class KnowledgeRelationResponse(BaseModel):
    """Knowledge relation with endpoint metadata."""

    id: int
    subject: str
    source_node_id: int
    source_node_name: str
    source_node_type: str
    target_node_id: int
    target_node_name: str
    target_node_type: str
    edge_type: str
    description: str = ""
    weight: float
    confidence: float


class FullGraphResponse(BaseModel):
    """Full graph payload for force-graph visualization."""

    nodes: list[KnowledgeUnitResponse] = Field(default_factory=list)
    edges: list[GraphEdgeResponse] = Field(default_factory=list)


class KnowledgePathResponse(BaseModel):
    """A path through the knowledge graph."""

    found: bool = False
    nodes: list[KnowledgeUnitResponse] = Field(default_factory=list)
    edges: list[KnowledgeRelationResponse] = Field(default_factory=list)


class KnowledgeSubgraphResponse(BaseModel):
    """Focused subgraph payload."""

    nodes: list[KnowledgeUnitResponse] = Field(default_factory=list)
    edges: list[KnowledgeRelationResponse] = Field(default_factory=list)
    center_knowledge_unit_id: int | None = None


class KnowledgeRelationEvidenceItem(BaseModel):
    """Evidence surfaced for one relation path step."""

    edge_id: int
    edge_type: str
    source_node_id: int
    target_node_id: int
    description: str = ""
    evidence: list[EvidenceSummary] = Field(default_factory=list)


class KnowledgeRelationExplanationResponse(BaseModel):
    """Explainable relation path result."""

    path: KnowledgePathResponse
    evidence: list[KnowledgeRelationEvidenceItem] = Field(default_factory=list)


class KnowledgeOverviewStats(BaseModel):
    """Knowledge overview stats."""

    node_count: int = 0
    edge_count: int = 0


class KnowledgeOverviewResponse(BaseModel):
    """Knowledge overview aggregated payload for summary tabs."""

    subject: str
    generated_at: datetime
    graph: FullGraphResponse | None = None
    stats: KnowledgeOverviewStats = Field(default_factory=KnowledgeOverviewStats)
    vector_status: SubjectVectorStatusResponse = Field(
        default_factory=SubjectVectorStatusResponse,
        description="Current subject-level vector capability status.",
    )
    planner_session_id: str | None = Field(default=None, description="Planner session id bound to this build.")
    confirmed_plan_id: str | None = Field(default=None, description="Confirmed build plan id bound to this build.")
    digest_mode: str | None = Field(default=None, description="Digest mode frozen in the confirmed build plan.")


class ClearKnowledgeResponse(BaseModel):
    """Knowledge clear response."""

    subject: str
    deleted_counts: dict[str, int] = Field(default_factory=dict)


class BuildPlannerCreateRequest(BaseModel):
    """Create a new planner session and generate the first plan draft."""

    file_uids: list[str] | None = Field(
        default=None,
        description=(
            "Optional uploaded file UIDs to bind to the planner session. Files may still be parsing; "
            "planner prefers parsed content and falls back to filenames/metadata when needed."
        ),
    )
    user_prompt: str = Field(description="Learner prompt or requested document target.")
    digest_mode: Literal["sprint", "systematic"] | None = Field(default=None, description="Optional requested digest mode.")
    title: str | None = Field(default=None, description="Optional planner session title.")


class BuildPlannerMessageRequest(BaseModel):
    """Append one planner revision message."""

    message: str = Field(description="User feedback used to revise the current plan draft.")


class BuildPlannerAdjustClickResponse(BaseModel):
    """Acknowledgement for entering planner adjustment mode."""

    acknowledged: bool = True
    planner_session_id: str
    subject: str
    status: str = ""
    has_latest_plan: bool = False
    latest_plan_chapter_count: int = 0


class BuildPlannerTurnResponse(BaseModel):
    id: int | None = None
    role: str
    content: str
    created_at: datetime


class BuildPlannerChapterPlanResponse(BaseModel):
    chapter_index: int
    title: str
    objective: str = ""
    required_elements: list[str] = Field(default_factory=list)
    writing_instructions: str = ""


class BuildPlannerStepStatsResponse(BaseModel):
    name: str
    status: str = "ok"
    elapsed_ms: int = 0


class BuildPlannerRuntimeStatsResponse(BaseModel):
    elapsed_ms: int = 0
    steps: list[BuildPlannerStepStatsResponse] = Field(default_factory=list)


class BuildPlannerPlanResponse(BaseModel):
    subject: str
    selected_file_uids: list[str] = Field(default_factory=list)
    user_prompt: str
    digest_mode: str
    chapter_plan: list[BuildPlannerChapterPlanResponse] = Field(default_factory=list)
    build_constraints: dict[str, object] = Field(default_factory=dict)
    plan_summary: str = ""
    status: str = "draft"
    planner_session_id: str | None = None
    confirmed_plan_id: str | None = None


class BuildPlannerSessionResponse(BaseModel):
    session_id: str
    subject: str
    title: str
    status: str
    revision: int
    latest_plan: BuildPlannerPlanResponse
    turns: list[BuildPlannerTurnResponse] = Field(default_factory=list)
    runtime_stats: BuildPlannerRuntimeStatsResponse | None = None
    created_at: datetime
    updated_at: datetime


class BuildPlannerConfirmResponse(BaseModel):
    planner_session_id: str
    confirmed_plan_id: str
    subject: str
    status: str
    digest_mode: str
    selected_file_uids: list[str] = Field(default_factory=list)
    selected_file_ids: list[int] = Field(default_factory=list)
    user_prompt: str
    plan_summary: str
    chapter_plan: list[BuildPlannerChapterPlanResponse] = Field(default_factory=list)
    build_constraints: dict[str, object] = Field(default_factory=dict)
    plan_json: dict[str, object] = Field(default_factory=dict)
    status_history: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
