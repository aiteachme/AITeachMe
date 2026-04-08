"""Knowledge-domain API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PageParams


class DocGenBuildRequest(BaseModel):
    """Trigger knowledge-doc generation."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "file_uids": ["file_xxx", "file_yyy"],
                "prompt": "Generate review-oriented notes",
                "embedding_resolution": "rebuild",
                "build_type": "all",
            }
        }
    )

    file_uids: list[str] | None = Field(
        default=None,
        description="Optional parsed raw file UIDs; omitted means auto-pick all available ready files for the subject. Ignored when `confirmed_plan_id` is provided.",
    )
    prompt: str | None = Field(default=None, description="Optional user instruction for doc generation. Ignored when `confirmed_plan_id` is provided and the confirmed plan already freezes the build goal.")
    embedding_resolution: Literal["rebuild", "disable"] | None = Field(
        default=None,
        description="Optional subject-level embedding resolution chosen after a precheck conflict.",
    )
    build_type: Literal["docs", "graph", "all"] = Field(
        default="all",
        description="Build type: 'docs' for knowledge documents only, 'graph' for knowledge graph + curriculum only, 'all' for unified build.",
    )
    confirmed_plan_id: str | None = Field(
        default=None,
        description="Planner 生成并确认后的构建方案 ID。`docs` 和 `all` 构建必须提供该字段；提供后会以方案冻结的文件选择、章节规划和用户目标作为正式构建契约。",
    )

class GraphNodesQueryRequest(PageParams):
    """Paginated graph node query."""

    node_type: str | None = Field(default=None, description="Optional node type filter.")


class GraphNodeDetailRequest(BaseModel):
    """Node detail query."""

    node_id: int = Field(description="Knowledge node ID.")


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


class UnitsQueryRequest(PageParams):
    """Paginated teaching-unit query."""

    status: str | None = Field(default=None, description="Optional status filter; defaults to active.")


class UnitDetailRequest(BaseModel):
    """Teaching-unit detail query."""

    unit_id: int = Field(description="Teaching unit ID.")


class AnchorManageRequest(BaseModel):
    """Taxonomy anchor management request."""

    action: str = Field(description="list / create / update / delete")
    anchor_id: int | None = Field(default=None, description="Anchor ID for update/delete.")
    title: str | None = Field(default=None, description="Anchor title for create/update.")
    anchor_type: str | None = Field(
        default=None,
        description="teacher_defined / syllabus / textbook_toc / graph_discovered",
    )
    parent_anchor_id: int | None = Field(default=None, description="Parent anchor ID.")
    order_index: int | None = Field(default=None, description="Order index.")


class KnowledgeBuildPrecheckConflictData(BaseModel):
    """Structured payload for one build-precheck conflict."""

    reason: str = Field(description="Stable reason code for the precheck conflict.")
    subject_model: str | None = Field(default=None, description="Subject-bound embedding model, if any.")
    subject_dim: int | None = Field(default=None, description="Subject-bound embedding dimension, if any.")
    runtime_model: str | None = Field(default=None, description="Current runtime embedding model, if any.")
    runtime_dim: int | None = Field(default=None, description="Current runtime embedding dimension, if any.")
    requires_full_rebuild: bool = Field(default=False, description="Whether restoring vector mode requires a full rebuild.")
    vector_enabled_after_continue: bool = Field(default=False, description="Whether vector mode stays enabled after continuing without rebuild.")


class SubjectVectorStatusResponse(BaseModel):
    """Subject-level vector capability status shown to the UI."""

    mode: str = Field(default="enabled", description="enabled / disabled")
    notice: str | None = Field(default=None, description="User-facing vector capability notice.")
    embedding_model: str | None = Field(default=None, description="Current subject-bound embedding model, if any.")
    vector_table: str | None = Field(default=None, description="Current subject-scoped vector table, if any.")


class DocGenBuildData(BaseModel):
    """Knowledge docs build response data."""

    accepted_file_uids: list[str] = Field(default_factory=list, description="Accepted ready raw file UIDs.")
    prompt: str | None = Field(default=None, description="Effective user prompt for the docs build after planner overrides are applied.")
    ready_file_count: int = Field(default=0, description="Current ready file count for this subject.")
    requested_at: datetime = Field(description="Build request timestamp.")
    vector_status: SubjectVectorStatusResponse = Field(
        default_factory=SubjectVectorStatusResponse,
        description="Current subject-level vector capability status.",
    )
    planner_session_id: str | None = Field(default=None, description="Planner session id bound to this build.")
    confirmed_plan_id: str | None = Field(default=None, description="Confirmed build plan id bound to this build.")
    digest_mode: str | None = Field(default=None, description="Digest mode frozen in the confirmed build plan.")

class BuildSampleCardResponse(BaseModel):
    """Lightweight preview card shown while digest is building."""

    title: str
    card_type: str = Field(description="mode / topic / concept / method")
    summary: str


class BuildPreviewNodeResponse(BaseModel):
    """One lightweight node preview surfaced during digest polling."""

    name: str
    node_type: str = Field(description="Topic / Concept / Method / Definition / Example")


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


class KnowledgeBuildPreviewResponse(BaseModel):
    """Human-facing preview payload for ongoing digest builds."""

    current_stage_description: str | None = Field(default=None, description="Friendly description of the current build stage.")
    digest_mode: str | None = Field(default=None, description="sprint / systematic")
    mode_reason: str | None = Field(default=None, description="Why the current digest mode was selected.")
    processed_chunks: int = Field(default=0, description="How many section chunks have been processed so far.")
    total_chunks: int = Field(default=0, description="Total number of section chunks for this build.")
    discovered_node_count: int = Field(default=0, description="Current discovered knowledge-node count.")
    discovered_node_types: dict[str, int] = Field(default_factory=dict, description="Node counts by node type.")
    sample_nodes: list[BuildPreviewNodeResponse] = Field(default_factory=list, description="Sample discovered nodes.")
    sample_cards: list[BuildSampleCardResponse] = Field(default_factory=list, description="Small preview cards for the waiting UI.")
    plan_summary: str | None = Field(default=None, description="Confirmed build plan summary for the current build.")
    chapter_progress: list[BuildPreviewChapterProgressResponse] = Field(default_factory=list, description="Per-chapter progress for the current build.")
    recent_events: list[BuildPreviewRecentEventResponse] = Field(default_factory=list, description="Recent research / writing / publishing events for the current build.")
    latest_chapter_titles: list[str] = Field(default_factory=list, description="Recently staged or published chapter titles.")
    draft_excerpt: str = Field(default="", description="Short excerpt from the current draft markdown, if any.")


class KnowledgeBuildMetricsResponse(BaseModel):
    """Compact build diagnostics used by polling UIs."""

    llm_total_calls: int = Field(default=0, description="Total LLM calls recorded for the current build session.")
    failed_llm_call_count: int = Field(default=0, description="Failed LLM call count for the current build session.")
    llm_avg_latency_ms: float = Field(default=0.0, description="Average LLM latency in milliseconds.")
    call_count_by_lane: dict[str, int] = Field(default_factory=dict, description="LLM call count grouped by workflow lane.")


class KnowledgeBuildStatusResponse(BaseModel):
    """Minimal runtime metadata exposed to clients for docs polling."""

    status: str = Field(description="idle / accepted / running / publishing / completed / failed / cancelled")
    requested_at: datetime = Field(description="Build request timestamp.")
    stage: str = Field(description="Current lifecycle stage for the build.")
    error_message: str | None = Field(default=None, description="Build failure or cancellation reason.")
    draft_available: bool = Field(default=False, description="Whether a staging draft is currently available.")
    planner_session_id: str | None = Field(default=None, description="Planner session id bound to the current build.")
    confirmed_plan_id: str | None = Field(default=None, description="Confirmed build plan id bound to the current build.")
    digest_mode: str | None = Field(default=None, description="Digest mode for the current build.")
    mode_reason: str | None = Field(default=None, description="Reason for the current digest mode.")
    current_stage_description: str | None = Field(default=None, description="Friendly description of the current build stage.")


class DocGenBuildStatusResponse(KnowledgeBuildStatusResponse):
    """Backward-compatible alias used by existing docs responses."""


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

class KnowledgeNodeResponse(BaseModel):
    """Knowledge node list item."""

    id: int
    subject: str
    node_type: str
    canonical_name: str
    status: str
    confidence: float
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


class NodeRevisionItem(BaseModel):
    """Current revision content for a knowledge node."""

    title: str
    summary: str
    body: str


class KnowledgeNodeDetailResponse(BaseModel):
    """Knowledge node detail response."""

    id: int
    subject: str
    node_type: str
    canonical_name: str
    normalized_name: str
    status: str
    confidence: float
    current_revision: NodeRevisionItem | None = None
    aliases: list[AliasItem] = Field(default_factory=list)
    evidence: list[EvidenceSummary] = Field(default_factory=list)
    incident_edges: list[IncidentEdgeItem] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class UnitMembershipItem(BaseModel):
    """Teaching-unit membership item."""

    id: int
    knowledge_node_id: int
    node_canonical_name: str
    node_type: str
    role: str
    score: float


class UnitRevisionItem(BaseModel):
    """Current revision for a teaching unit."""

    title: str
    summary: str
    learning_objectives: list[str] = Field(default_factory=list)


class TeachingUnitResponse(BaseModel):
    """Teaching-unit list item."""

    id: int
    subject: str
    canonical_name: str
    status: str
    confidence: float
    created_at: datetime
    updated_at: datetime


class TeachingUnitDetailResponse(BaseModel):
    """Teaching-unit detail response."""

    id: int
    subject: str
    canonical_name: str
    normalized_name: str
    member_signature: str
    status: str
    confidence: float
    current_revision: UnitRevisionItem | None = None
    members: list[UnitMembershipItem] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class TaxonomyAnchorResponse(BaseModel):
    """Taxonomy anchor response."""

    id: int
    subject: str
    anchor_type: str
    title: str
    parent_anchor_id: int | None = None
    order_index: int
    confidence: float
    is_system: bool
    status: str
    created_at: datetime
    updated_at: datetime


class ThemeTreeNodeResponse(BaseModel):
    """Theme-tree node response."""

    id: int
    tree_version_id: int
    anchor_id: int | None = None
    parent_tree_node_id: int | None = None
    title: str
    node_type: str
    order_index: int
    summary: str
    children: list["ThemeTreeNodeResponse"] = Field(default_factory=list)
    units: list["TreeUnitItem"] = Field(default_factory=list)


class TreeUnitItem(BaseModel):
    """Teaching-unit mount info in theme tree."""

    teaching_unit_id: int
    canonical_name: str
    membership_role: str
    membership_source: str
    score: float


class ThemeTreeResponse(BaseModel):
    """Current published theme tree response."""

    version_id: int
    version_no: int
    subject: str
    status: str
    created_at: datetime
    tree: list[ThemeTreeNodeResponse] = Field(default_factory=list)


class CurriculumSnapshotResponse(BaseModel):
    """Current curriculum snapshot response."""

    id: int
    subject: str
    version_no: int
    status: str
    theme_tree_version_id: int | None = None
    prereq_dag_version_id: int | None = None
    syllabus_version_id: int | None = None
    created_at: datetime


class UnitDependencyItem(BaseModel):
    """Dependency edge item in prereq DAG."""

    id: int
    source_unit_id: int
    source_unit_name: str
    target_unit_id: int
    target_unit_name: str
    dependency_type: str
    confidence: float
    supporting_edge_count: int


class PrereqDagResponse(BaseModel):
    """Current published prereq DAG response."""

    version_id: int
    version_no: int
    subject: str
    status: str
    created_at: datetime
    dependencies: list[UnitDependencyItem] = Field(default_factory=list)


class GraphEdgeResponse(BaseModel):
    """Graph edge item used by full-graph query."""

    id: int
    source_node_id: int
    target_node_id: int
    edge_type: str
    weight: float
    confidence: float


class FullGraphResponse(BaseModel):
    """Full graph payload for force-graph visualization."""

    nodes: list[KnowledgeNodeResponse] = Field(default_factory=list)
    edges: list[GraphEdgeResponse] = Field(default_factory=list)


class KnowledgeOverviewStats(BaseModel):
    """Knowledge overview stats."""

    node_count: int = 0
    edge_count: int = 0
    unit_count: int = 0
    theme_node_count: int = 0
    dependency_count: int = 0


class KnowledgeOverviewResponse(BaseModel):
    """Knowledge overview aggregated payload for summary tabs."""

    subject: str
    generated_at: datetime
    snapshot: CurriculumSnapshotResponse | None = None
    theme_tree: ThemeTreeResponse | None = None
    prereq_dag: PrereqDagResponse | None = None
    graph: FullGraphResponse | None = None
    units: list[TeachingUnitResponse] = Field(default_factory=list)
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


class StudyPlanRequest(BaseModel):
    """Read or update the persisted study plan in one POST request."""

    item_id: str | None = None
    completed: bool | None = None


class StudyPlanItemResponse(BaseModel):
    """One actionable study checklist item."""

    id: str
    title: str
    summary: str
    duration_minutes: int = 0
    depends_on_ids: list[str] = Field(default_factory=list)
    theme_titles: list[str] = Field(default_factory=list)
    unit_ids: list[int] = Field(default_factory=list)
    doc_anchor: str | None = None
    completed: bool = False


class StudyPlanPhaseResponse(BaseModel):
    """A grouped phase in the learner-facing study plan."""

    id: str
    title: str
    summary: str
    duration_minutes: int = 0
    completed_items: int = 0
    total_items: int = 0
    items: list[StudyPlanItemResponse] = Field(default_factory=list)


class StudyPlanResponse(BaseModel):
    """Derived study plan and checklist snapshot."""

    subject: str
    generated_at: datetime
    digest_mode: str | None = None
    mode_reason: str | None = None
    total_items: int = 0
    completed_items: int = 0
    phases: list[StudyPlanPhaseResponse] = Field(default_factory=list)


ThemeTreeNodeResponse.model_rebuild()



class BuildPlannerCreateRequest(BaseModel):
    """Create a new planner session and generate the first plan draft."""

    file_uids: list[str] | None = Field(default=None, description="Optional uploaded file UIDs to bind to the planner session. Files may still be parsing; planner 会优先使用已解析内容，不足时退化到文件名与资料元信息。")
    user_goal: str = Field(description="Learner goal or requested document target.")
    digest_mode: Literal["sprint", "systematic"] | None = Field(default=None, description="Optional requested digest mode.")
    tone: str | None = Field(default=None, description="Optional requested writing tone.")
    title: str | None = Field(default=None, description="Optional planner session title.")


class BuildPlannerMessageRequest(BaseModel):
    """Append one planner revision message."""

    message: str = Field(description="User feedback used to revise the current plan draft.")


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
    search_queries: list[str] = Field(default_factory=list)
    writing_instructions: str = ""
    media_hints: dict[str, list[str]] = Field(default_factory=dict)


class BuildPlannerNodeTimingResponse(BaseModel):
    node_name: str
    lane: str = "planner"
    workflow: str = "digest.planner"
    elapsed_ms: int = 0
    status: str = "ok"


class BuildPlannerRuntimeStatsResponse(BaseModel):
    workflow_elapsed_ms: int = 0
    node_timings_ms: dict[str, int] = Field(default_factory=dict)
    node_events: list[BuildPlannerNodeTimingResponse] = Field(default_factory=list)
    fallback_used: bool = False
    generation_mode: str | None = None


class BuildPlannerPlanResponse(BaseModel):
    subject: str
    selected_file_uids: list[str] = Field(default_factory=list)
    user_goal: str
    digest_mode: str
    tone: str
    chapter_plan: list[BuildPlannerChapterPlanResponse] = Field(default_factory=list)
    research_queries: list[str] = Field(default_factory=list)
    media_plan: dict[str, object] = Field(default_factory=dict)
    build_constraints: dict[str, object] = Field(default_factory=dict)
    plan_summary: str = ""
    status: str = "draft"
    planner_session_id: str | None = None
    confirmed_plan_id: str | None = None


class BuildPlannerSessionResponse(BaseModel):
    session_id: str
    title: str
    status: str
    plan: BuildPlannerPlanResponse
    turns: list[BuildPlannerTurnResponse] = Field(default_factory=list)
    runtime_stats: BuildPlannerRuntimeStatsResponse | None = None


class BuildPlannerConfirmResponse(BaseModel):
    session_id: str
    plan_id: str
    plan: BuildPlannerPlanResponse

