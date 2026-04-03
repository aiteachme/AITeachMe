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
            }
        }
    )

    file_uids: list[str] | None = Field(
        default=None,
        description="Optional parsed raw file UIDs; omitted means auto-pick all available files for the subject.",
    )
    prompt: str | None = Field(default=None, description="Optional user instruction for doc generation.")
    embedding_resolution: Literal["rebuild", "disable"] | None = Field(
        default=None,
        description="Optional subject-level embedding resolution chosen after a precheck conflict.",
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
    prompt: str | None = Field(default=None, description="User prompt for the docs build.")
    ready_file_count: int = Field(default=0, description="Current ready file count for this subject.")
    requested_at: datetime = Field(description="Build request timestamp.")
    vector_status: SubjectVectorStatusResponse = Field(
        default_factory=SubjectVectorStatusResponse,
        description="Current subject-level vector capability status.",
    )

class DocGenBuildStatusResponse(BaseModel):
    """Runtime metadata for the current or most recent docs build."""

    status: str = Field(description="accepted / running / completed / failed / cancelled")
    requested_at: datetime = Field(description="Build request timestamp.")
    stage: str = Field(description="Current lifecycle stage for the build.")
    error_message: str | None = Field(default=None, description="Build failure or cancellation reason.")
    draft_available: bool = Field(default=False, description="Whether the current staging draft can be previewed.")


class DocGenGetResponse(BaseModel):
    """Knowledge docs get response."""

    exists: bool = Field(description="Whether a merged knowledge document exists.")
    markdown: str = Field(default="", description="Merged markdown content.")
    updated_at: datetime | None = Field(default=None, description="Last updated time of the merged markdown.")
    source_file_uids: list[str] = Field(default_factory=list, description="Source raw file UIDs used by the published docs.")
    prompt: str | None = Field(default=None, description="User prompt used for the published docs.")
    draft_markdown: str = Field(default="", description="Current staging draft markdown content, if available.")
    draft_updated_at: datetime | None = Field(default=None, description="Last updated time of the staging draft.")
    build: DocGenBuildStatusResponse | None = Field(default=None, description="Current or most recent build metadata.")
    vector_status: SubjectVectorStatusResponse = Field(
        default_factory=SubjectVectorStatusResponse,
        description="Current subject-level vector capability status.",
    )

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

class ClearKnowledgeResponse(BaseModel):
    """Knowledge clear response."""

    subject: str
    deleted_counts: dict[str, int] = Field(default_factory=dict)


ThemeTreeNodeResponse.model_rebuild()

