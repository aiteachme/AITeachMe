"""知识图谱增量构建 API Schema（Phase 1）。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PageParams


# ── 请求 ──


class DigestBuildRequest(BaseModel):
    """触发增量构建请求。"""

    model_config = ConfigDict(
        json_schema_extra={"example": {"file_ids": [1, 2], "idempotency_key": "abc123"}}
    )

    file_ids: list[int] = Field(min_length=1, description="参与构建的已解析文件 ID。")
    idempotency_key: str | None = Field(
        default=None, description="幂等键，为空时由服务端生成。",
    )


class DigestStatusRequest(BaseModel):
    """查询增量构建状态请求。"""

    job_id: int = Field(description="GraphDigestJob ID。")


class DocGenBuildRequest(BaseModel):
    """触发知识文档生成请求。"""

    model_config = ConfigDict(
        json_schema_extra={"example": {"file_ids": [1, 2]}}
    )

    file_ids: list[int] = Field(min_length=1, description="参与生成的已解析文件 ID。")


class DocGenStatusRequest(BaseModel):
    """查询知识文档生成状态请求。"""

    job_id: int = Field(description="DocGenJob ID。")


class GraphNodesQueryRequest(PageParams):
    """分页查询知识节点请求。"""

    node_type: str | None = Field(default=None, description="按节点类型过滤。")


class GraphNodeDetailRequest(BaseModel):
    """知识节点详情请求。"""

    node_id: int = Field(description="知识节点 ID。")


# ── 响应 ──


class DigestBuildData(BaseModel):
    """触发增量构建返回数据。"""

    job_id: int = Field(description="GraphDigestJob ID。")
    is_existing: bool = Field(default=False, description="是否命中幂等键返回已有 job。")


class GraphDigestJobResponse(BaseModel):
    """GraphDigestJob 状态。"""

    id: int
    subject: str
    status: str
    progress: int
    current_step: str | None = None
    input_chunk_count: int = 0
    nodes_added: int = 0
    nodes_updated: int = 0
    nodes_merged: int = 0
    edges_added: int = 0
    edges_updated: int = 0
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class CurriculumJobResponse(BaseModel):
    """CurriculumDeriveJob 状态。"""

    id: int
    subject: str
    graph_job_id: int
    status: str
    progress: int
    current_step: str | None = None
    units_added: int = 0
    units_updated: int = 0
    theme_tree_version_id: int | None = None
    prereq_dag_version_id: int | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class DocGenBuildData(BaseModel):
    """触发文档生成返回数据。"""

    job_id: int = Field(description="DocGenJob ID。")


class DocGenJobResponse(BaseModel):
    """DocGenJob 状态。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    subject: str
    status: str
    progress: int
    current_step: str | None = None
    total_chapters: int = 0
    completed_chapters: int = 0
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class DocGenStatusResponse(BaseModel):
    """知识文档生成状态响应。"""

    job: DocGenJobResponse


class DocGenContentResponse(BaseModel):
    """知识文档生成产物响应。"""

    markdown: str = Field(description="合并后的最终 Markdown 内容。")


class DigestStatusResponse(BaseModel):
    """增量构建聚合状态：graph_job + curriculum_job + 当前快照。"""

    graph_job: GraphDigestJobResponse
    curriculum_job: CurriculumJobResponse | None = None
    current_curriculum_snapshot_id: int | None = None


class KnowledgeNodeResponse(BaseModel):
    """知识节点列表项。"""

    id: int
    subject: str
    node_type: str
    canonical_name: str
    status: str
    confidence: float
    created_at: datetime
    updated_at: datetime


class EvidenceSummary(BaseModel):
    """证据摘要（用于节点详情）。"""

    id: int
    document_id: int
    chunk_id: int
    quote_text: str
    evidence_role: str
    field_scope: str
    confidence: float


class EvidenceContextRequest(BaseModel):
    """证据上下文请求。"""

    evidence_id: int = Field(description="EvidenceLink ID。")


class EvidenceContextResponse(BaseModel):
    """证据上下文响应：chunk markdown + 高亮位置。"""

    evidence_id: int
    document_id: int
    document_title: str
    chunk_id: int
    chunk_title: str
    chunk_header_path: str
    chunk_content: str
    quote_text: str
    highlight_start: int | None = None
    highlight_end: int | None = None


class ChunkContextRequest(BaseModel):
    """Chat chunk context request."""

    chunk_id: int = Field(description="Document chunk ID.")


class ChunkContextResponse(BaseModel):
    """Chat chunk context response."""

    chunk_id: int
    document_id: int
    document_title: str
    chunk_title: str
    chunk_header_path: str
    chunk_content: str


class AliasItem(BaseModel):
    """别名项。"""

    id: int
    alias: str
    language: str
    source: str
    confidence: float
    is_primary: bool


class IncidentEdgeItem(BaseModel):
    """关联边项。"""

    id: int
    edge_type: str
    direction: str = Field(description="outgoing 或 incoming。")
    other_node_id: int
    other_node_name: str
    other_node_type: str
    confidence: float


class NodeRevisionItem(BaseModel):
    """节点当前修订。"""

    title: str
    summary: str
    body: str


class KnowledgeNodeDetailResponse(BaseModel):
    """知识节点详情。"""

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


# ── Phase 2: 教学单元 ──


class UnitsQueryRequest(PageParams):
    """分页查询教学单元请求。"""

    status: str | None = Field(default=None, description="按状态过滤（默认仅 active）。")


class UnitDetailRequest(BaseModel):
    """教学单元详情请求。"""

    unit_id: int = Field(description="教学单元 ID。")


class UnitMembershipItem(BaseModel):
    """教学单元成员节点。"""

    id: int
    knowledge_node_id: int
    node_canonical_name: str
    node_type: str
    role: str
    score: float


class UnitRevisionItem(BaseModel):
    """教学单元当前修订。"""

    title: str
    summary: str
    learning_objectives: list[str] = Field(default_factory=list)


class TeachingUnitResponse(BaseModel):
    """教学单元列表项。"""

    id: int
    subject: str
    canonical_name: str
    status: str
    confidence: float
    created_at: datetime
    updated_at: datetime


class TeachingUnitDetailResponse(BaseModel):
    """教学单元详情。"""

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


# ── Phase 3: 主题树 ──


class AnchorManageRequest(BaseModel):
    """锚点管理请求。"""

    action: str = Field(description="操作类型：list / create / update / delete。")
    anchor_id: int | None = Field(default=None, description="锚点 ID（update/delete 时必填）。")
    title: str | None = Field(default=None, description="锚点标题（create/update 时使用）。")
    anchor_type: str | None = Field(
        default=None,
        description="锚点类型：teacher_defined / syllabus / textbook_toc / graph_discovered。",
    )
    parent_anchor_id: int | None = Field(default=None, description="父锚点 ID。")
    order_index: int | None = Field(default=None, description="排序索引。")


class TaxonomyAnchorResponse(BaseModel):
    """分类锚点响应。"""

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
    """主题树节点响应。"""

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
    """主题树中挂载的教学单元。"""

    teaching_unit_id: int
    canonical_name: str
    membership_role: str
    membership_source: str
    score: float


class ThemeTreeResponse(BaseModel):
    """当前主题树响应。"""

    version_id: int
    version_no: int
    subject: str
    status: str
    created_at: datetime
    tree: list[ThemeTreeNodeResponse] = Field(default_factory=list)


class CurriculumSnapshotResponse(BaseModel):
    """课程快照响应。"""

    id: int
    subject: str
    version_no: int
    status: str
    theme_tree_version_id: int | None = None
    prereq_dag_version_id: int | None = None
    syllabus_version_id: int | None = None
    created_at: datetime


# ── Phase 4: 先修 DAG ──


class UnitDependencyItem(BaseModel):
    """先修 DAG 中的依赖边。"""

    id: int
    source_unit_id: int
    source_unit_name: str
    target_unit_id: int
    target_unit_name: str
    dependency_type: str
    confidence: float
    supporting_edge_count: int


class PrereqDagResponse(BaseModel):
    """当前先修 DAG 响应。"""

    version_id: int
    version_no: int
    subject: str
    status: str
    created_at: datetime
    dependencies: list[UnitDependencyItem] = Field(default_factory=list)


class GraphEdgeResponse(BaseModel):
    """知识边列表项（用于全图查询）。"""

    id: int
    source_node_id: int
    target_node_id: int
    edge_type: str
    weight: float
    confidence: float


class FullGraphResponse(BaseModel):
    """完整知识图谱（节点 + 边），用于力导向图可视化。"""

    nodes: list[KnowledgeNodeResponse] = Field(default_factory=list)
    edges: list[GraphEdgeResponse] = Field(default_factory=list)


class ClearKnowledgeResponse(BaseModel):
    """清空知识数据响应。"""

    subject: str
    deleted_counts: dict[str, int] = Field(default_factory=dict)


# Rebuild forward refs for recursive model
ThemeTreeNodeResponse.model_rebuild()
