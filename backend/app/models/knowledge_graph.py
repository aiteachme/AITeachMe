"""知识图谱数据模型：节点、边、修订、证据、构建任务与构建锁。"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, Index, SQLModel, UniqueConstraint

from app.utils.time import utcnow


class KnowledgeNode(SQLModel, table=True):
    """知识节点：身份 + 路由 + 状态，不存内容（内容由 KnowledgeRevision 承载）。"""

    __tablename__ = "knowledge_node"
    __table_args__ = (
        UniqueConstraint(
            "subject", "node_type", "normalized_name",
            name="uq_node_subject_type_name",
        ),
        Index("ix_node_subject_status", "subject", "status"),
    )

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    node_type: str = Field(index=True)  # KGNodeType
    canonical_name: str
    normalized_name: str = Field(index=True)
    status: str = Field(default="pending")  # KGNodeStatus
    confidence: float = Field(default=1.0)
    current_revision_id: int | None = Field(default=None)
    merged_into_node_id: int | None = Field(
        default=None, foreign_key="knowledge_node.id",
    )
    created_by_job_id: int | None = Field(
        default=None, foreign_key="graph_digest_job.id", index=True,
    )
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class KnowledgeAlias(SQLModel, table=True):
    """知识节点别名，独立表支持高效索引。"""

    __tablename__ = "knowledge_alias"
    __table_args__ = (
        UniqueConstraint(
            "node_id", "normalized_alias",
            name="uq_alias_node_normalized",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    node_id: int = Field(foreign_key="knowledge_node.id", index=True)
    alias: str
    normalized_alias: str = Field(index=True)
    language: str = Field(default="zh")
    source: str = Field(default="llm")  # ExtractionMethod
    confidence: float = Field(default=1.0)
    is_primary: bool = Field(default=False)
    status: str = Field(default="active")  # AliasStatus
    created_by_job_id: int | None = Field(
        default=None, foreign_key="graph_digest_job.id", index=True,
    )
    created_at: datetime = Field(default_factory=utcnow)


class KnowledgeEdge(SQLModel, table=True):
    """知识边：两个节点之间的有向关系。"""

    __tablename__ = "knowledge_edge"
    __table_args__ = (
        UniqueConstraint(
            "subject", "source_node_id", "target_node_id", "edge_type",
            name="uq_edge_subject_src_tgt_type",
        ),
        Index("ix_edge_subject_status", "subject", "status"),
    )

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    source_node_id: int = Field(foreign_key="knowledge_node.id", index=True)
    target_node_id: int = Field(foreign_key="knowledge_node.id", index=True)
    edge_type: str = Field(index=True)  # KGEdgeType
    weight: float = Field(default=1.0)
    confidence: float = Field(default=0.5)
    status: str = Field(default="pending")  # KGEdgeStatus
    current_revision_id: int | None = Field(default=None)
    created_by_job_id: int | None = Field(
        default=None, foreign_key="graph_digest_job.id", index=True,
    )
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class KnowledgeRevision(SQLModel, table=True):
    """知识节点的版本化修订记录。"""

    __tablename__ = "knowledge_revision"
    __table_args__ = (
        UniqueConstraint("node_id", "revision_no", name="uq_node_revision_no"),
        Index("ix_revision_node_current", "node_id", "is_current"),
    )

    id: int | None = Field(default=None, primary_key=True)
    node_id: int = Field(foreign_key="knowledge_node.id", index=True)
    revision_no: int
    title: str
    summary: str = ""
    body: str = ""
    revision_reason: str  # RevisionReason
    digest_job_id: int | None = Field(
        default=None, foreign_key="graph_digest_job.id",
    )
    is_current: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow)


class EdgeRevision(SQLModel, table=True):
    """知识边的版本化修订记录。"""

    __tablename__ = "edge_revision"
    __table_args__ = (
        UniqueConstraint("edge_id", "revision_no", name="uq_edge_revision_no"),
        Index("ix_edge_revision_edge_current", "edge_id", "is_current"),
    )

    id: int | None = Field(default=None, primary_key=True)
    edge_id: int = Field(foreign_key="knowledge_edge.id", index=True)
    revision_no: int
    description: str
    weight: float
    confidence: float
    revision_reason: str  # RevisionReason
    digest_job_id: int | None = Field(
        default=None, foreign_key="graph_digest_job.id",
    )
    is_current: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow)


class EvidenceLink(SQLModel, table=True):
    """证据链接。采用 polymorphic association（entity_type + entity_id），
    DB 层不做外键强约束到 node/edge，完整性由服务层保证。"""

    __tablename__ = "evidence_link"
    __table_args__ = (
        Index("ix_evidence_entity", "entity_type", "entity_id", "is_active"),
    )

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    entity_type: str  # "node" | "edge"
    entity_id: int = Field(index=True)
    entity_revision_id: int | None = Field(default=None)
    document_id: int = Field(foreign_key="document.id")
    chunk_id: int = Field(foreign_key="document_chunk.id")
    quote_text: str = ""
    source_span_start: int | None = Field(default=None)
    source_span_end: int | None = Field(default=None)
    evidence_role: str  # EvidenceRole
    extraction_method: str = Field(default="llm")  # ExtractionMethod
    field_scope: str = Field(default="summary")  # FieldScope
    confidence: float = Field(default=1.0)
    is_active: bool = Field(default=True)
    created_by_job_id: int | None = Field(
        default=None, foreign_key="graph_digest_job.id", index=True,
    )
    created_at: datetime = Field(default_factory=utcnow)


class GraphDigestJob(SQLModel, table=True):
    """图谱增量构建任务。"""

    __tablename__ = "graph_digest_job"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    idempotency_key: str = Field(index=True, unique=True)
    status: str = Field(default="pending")  # DigestJobStatus
    progress: int = Field(default=0)
    current_step: str | None = Field(default=None)
    input_file_ids_json: str = Field(default="[]")
    input_chunk_count: int = Field(default=0)
    extractor_version: str = Field(default="v1")
    embedding_model_version: str = Field(default="")
    nodes_added: int = Field(default=0)
    nodes_updated: int = Field(default=0)
    nodes_merged: int = Field(default=0)
    edges_added: int = Field(default=0)
    edges_updated: int = Field(default=0)
    curriculum_job_id: int | None = Field(
        default=None, foreign_key="curriculum_derive_job.id",
    )
    retry_of_job_id: int | None = Field(
        default=None, foreign_key="graph_digest_job.id",
    )
    error_message: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class SubjectBuildLock(SQLModel, table=True):
    """学科级构建锁，防止同一学科并发构建。"""

    __tablename__ = "subject_build_lock"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(unique=True)
    job_id: int | None = Field(default=None)
    locked_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime | None = Field(default=None)
