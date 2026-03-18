"""课程结构数据模型：教学单元、主题树、先修 DAG、课程快照与派生任务。"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel, UniqueConstraint


# ── 课程派生任务（需先于其他表定义，因为多表 FK 引用它） ──


class CurriculumDeriveJob(SQLModel, table=True):
    """课程结构派生任务（替代原 TreeDeriveJob）。"""

    __tablename__ = "curriculum_derive_job"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    graph_job_id: int = Field(foreign_key="graph_digest_job.id")
    status: str = Field(default="pending")  # DigestJobStatus
    progress: int = Field(default=0)
    current_step: str | None = Field(default=None)
    units_added: int = Field(default=0)
    units_updated: int = Field(default=0)
    theme_tree_version_id: int | None = Field(default=None)
    prereq_dag_version_id: int | None = Field(default=None)
    error_message: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ── 教学单元 ──


class TeachingUnit(SQLModel, table=True):
    """教学单元：一组紧密相关的知识节点组成的最小可讲授单位（leaf-only）。"""

    __tablename__ = "teaching_unit"
    __table_args__ = (
        UniqueConstraint(
            "subject", "member_signature",
            name="uq_unit_subject_signature",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    canonical_name: str
    normalized_name: str = Field(index=True)
    member_signature: str = Field(index=True)
    status: str = Field(default="pending")  # UnitStatus
    confidence: float = Field(default=1.0)
    current_revision_id: int | None = Field(default=None)
    created_by_job_id: int | None = Field(
        default=None, foreign_key="curriculum_derive_job.id", index=True,
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TeachingUnitRevision(SQLModel, table=True):
    """教学单元的版本化修订记录。"""

    __tablename__ = "teaching_unit_revision"
    __table_args__ = (
        UniqueConstraint("unit_id", "revision_no", name="uq_unit_revision_no"),
    )

    id: int | None = Field(default=None, primary_key=True)
    unit_id: int = Field(foreign_key="teaching_unit.id", index=True)
    revision_no: int
    title: str
    summary: str = ""
    learning_objectives_json: str = Field(default="[]")
    revision_reason: str  # RevisionReason
    curriculum_job_id: int | None = Field(
        default=None, foreign_key="curriculum_derive_job.id",
    )
    is_current: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TeachingUnitMembership(SQLModel, table=True):
    """知识节点在教学单元中的归属。"""

    __tablename__ = "teaching_unit_membership"
    __table_args__ = (
        UniqueConstraint(
            "unit_id", "knowledge_node_id", "role",
            name="uq_unit_node_role",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    unit_id: int = Field(foreign_key="teaching_unit.id", index=True)
    knowledge_node_id: int = Field(foreign_key="knowledge_node.id", index=True)
    role: str  # UnitMemberRole
    score: float = Field(default=0.0)
    created_by_job_id: int | None = Field(
        default=None, foreign_key="curriculum_derive_job.id", index=True,
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── 分类锚点 ──


class TaxonomyAnchor(SQLModel, table=True):
    """分类锚点，作为软约束骨架（不参与 cleanup_pending_by_job）。"""

    __tablename__ = "taxonomy_anchor"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    anchor_type: str  # AnchorType
    title: str
    normalized_title: str = Field(index=True)
    parent_anchor_id: int | None = Field(
        default=None, foreign_key="taxonomy_anchor.id",
    )
    order_index: int = Field(default=0)
    confidence: float = Field(default=1.0)
    is_system: bool = Field(default=False)
    status: str = Field(default="active")  # AnchorStatus
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ── 主题树 ──


class ThemeTreeVersion(SQLModel, table=True):
    """主题树版本化快照。"""

    __tablename__ = "theme_tree_version"
    __table_args__ = (
        UniqueConstraint(
            "subject", "version_no",
            name="uq_theme_tree_subject_version",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    version_no: int
    status: str = Field(default="draft")  # TreeVersionStatus
    curriculum_job_id: int | None = Field(
        default=None, foreign_key="curriculum_derive_job.id",
    )
    created_by_job_id: int | None = Field(
        default=None, foreign_key="curriculum_derive_job.id", index=True,
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ThemeTreeNode(SQLModel, table=True):
    """主题树节点，负责全部层级结构（chapter → section → theme → unit_bucket）。"""

    __tablename__ = "theme_tree_node"

    id: int | None = Field(default=None, primary_key=True)
    tree_version_id: int = Field(foreign_key="theme_tree_version.id", index=True)
    anchor_id: int | None = Field(
        default=None, foreign_key="taxonomy_anchor.id",
    )
    parent_tree_node_id: int | None = Field(
        default=None, foreign_key="theme_tree_node.id",
    )
    title: str
    node_type: str  # ThemeTreeNodeType
    order_index: int = Field(default=0)
    summary: str = ""
    created_by_job_id: int | None = Field(
        default=None, foreign_key="curriculum_derive_job.id", index=True,
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


class UnitTreeMembership(SQLModel, table=True):
    """教学单元在主题树中的归属。挂载 TeachingUnit 而非 KnowledgeNode。"""

    __tablename__ = "unit_tree_membership"
    __table_args__ = (
        UniqueConstraint(
            "tree_version_id", "tree_node_id", "teaching_unit_id", "membership_role",
            name="uq_tree_unit_role",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    tree_version_id: int = Field(foreign_key="theme_tree_version.id", index=True)
    tree_node_id: int = Field(foreign_key="theme_tree_node.id", index=True)
    teaching_unit_id: int = Field(foreign_key="teaching_unit.id", index=True)
    membership_role: str  # UnitTreeMembershipRole
    membership_source: str = Field(default="auto")  # MembershipSource
    score: float = Field(default=0.0)
    created_by_job_id: int | None = Field(
        default=None, foreign_key="curriculum_derive_job.id", index=True,
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── 先修 DAG ──


class PrereqDagVersion(SQLModel, table=True):
    """先修 DAG 版本化快照。"""

    __tablename__ = "prereq_dag_version"
    __table_args__ = (
        UniqueConstraint(
            "subject", "version_no",
            name="uq_prereq_dag_subject_version",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    version_no: int
    status: str = Field(default="draft")  # TreeVersionStatus
    curriculum_job_id: int | None = Field(
        default=None, foreign_key="curriculum_derive_job.id",
    )
    created_by_job_id: int | None = Field(
        default=None, foreign_key="curriculum_derive_job.id", index=True,
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


class UnitDependency(SQLModel, table=True):
    """教学单元之间的先修依赖边。"""

    __tablename__ = "unit_dependency"
    __table_args__ = (
        UniqueConstraint(
            "dag_version_id", "source_unit_id", "target_unit_id", "dependency_type",
            name="uq_dag_dep",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    dag_version_id: int = Field(foreign_key="prereq_dag_version.id", index=True)
    source_unit_id: int = Field(foreign_key="teaching_unit.id", index=True)
    target_unit_id: int = Field(foreign_key="teaching_unit.id", index=True)
    dependency_type: str = Field(default="prerequisite")  # DependencyType
    confidence: float = Field(default=0.5)
    supporting_edge_count: int = Field(default=0)
    derivation_metadata_json: str = Field(default="{}")
    created_by_job_id: int | None = Field(
        default=None, foreign_key="curriculum_derive_job.id", index=True,
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── 课程快照 ──


class CurriculumSnapshot(SQLModel, table=True):
    """课程视图一致性快照：记录当前课程结构 = 哪个 tree version + 哪个 dag version 的组合。"""

    __tablename__ = "curriculum_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "subject", "version_no",
            name="uq_curriculum_snapshot_subject_version",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    version_no: int
    status: str = Field(default="draft")  # TreeVersionStatus
    curriculum_job_id: int = Field(foreign_key="curriculum_derive_job.id")
    theme_tree_version_id: int | None = Field(
        default=None, foreign_key="theme_tree_version.id",
    )
    prereq_dag_version_id: int | None = Field(
        default=None, foreign_key="prereq_dag_version.id",
    )
    syllabus_version_id: int | None = Field(default=None)  # MVP-2 预留
    created_by_job_id: int | None = Field(
        default=None, foreign_key="curriculum_derive_job.id", index=True,
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
