"""Curriculum structure models."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel, UniqueConstraint

from app.utils.time import utcnow


class TeachingUnit(SQLModel, table=True):
    """Teach-able unit grouped from knowledge nodes."""

    __tablename__ = "teaching_unit"
    __table_args__ = (
        UniqueConstraint("subject", "member_signature", name="uq_unit_subject_signature"),
    )

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    canonical_name: str
    normalized_name: str = Field(index=True)
    member_signature: str = Field(index=True)
    title: str = ""
    summary: str = ""
    body_markdown: str = ""
    learning_objectives_json: str = Field(default="[]")
    member_node_refs_json: str = Field(default="[]")
    prerequisite_unit_ids_json: str = Field(default="[]")
    status: str = Field(default="pending")
    confidence: float = Field(default=1.0)
    current_revision_id: int | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class TeachingUnitRevision(SQLModel):
    """Structured current revision payload derived from teaching_unit."""

    id: int | None = None
    unit_id: int
    revision_no: int
    title: str
    summary: str = ""
    learning_objectives_json: str = Field(default="[]")
    revision_reason: str
    is_current: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow)


class TeachingUnitMembership(SQLModel):
    """Structured membership payload embedded on a teaching unit."""

    id: int | None = None
    unit_id: int
    knowledge_node_id: int
    role: str
    score: float = Field(default=0.0)
    created_at: datetime = Field(default_factory=utcnow)


class TaxonomyAnchor(SQLModel, table=True):
    """Curriculum anchor definition."""

    __tablename__ = "taxonomy_anchor"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    anchor_type: str
    title: str
    normalized_title: str = Field(index=True)
    parent_anchor_id: int | None = Field(default=None, foreign_key="taxonomy_anchor.id")
    order_index: int = Field(default=0)
    confidence: float = Field(default=1.0)
    is_system: bool = Field(default=False)
    status: str = Field(default="active")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ThemeTreeVersion(SQLModel, table=True):
    """Theme tree version."""

    __tablename__ = "theme_tree_version"
    __table_args__ = (
        UniqueConstraint("subject", "version_no", name="uq_theme_tree_subject_version"),
    )

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    version_no: int
    status: str = Field(default="draft")
    created_at: datetime = Field(default_factory=utcnow)


class ThemeTreeNode(SQLModel, table=True):
    """Theme tree node."""

    __tablename__ = "theme_tree_node"

    id: int | None = Field(default=None, primary_key=True)
    tree_version_id: int = Field(foreign_key="theme_tree_version.id", index=True)
    anchor_id: int | None = Field(default=None, foreign_key="taxonomy_anchor.id")
    parent_tree_node_id: int | None = Field(default=None, foreign_key="theme_tree_node.id")
    title: str
    node_type: str
    order_index: int = Field(default=0)
    summary: str = ""
    unit_refs_json: str = Field(default="[]")
    created_at: datetime = Field(default_factory=utcnow)


class UnitTreeMembership(SQLModel):
    """Structured unit mount payload embedded on a theme-tree node."""

    id: int | None = None
    tree_version_id: int
    tree_node_id: int
    teaching_unit_id: int
    membership_role: str
    membership_source: str = Field(default="auto")
    score: float = Field(default=0.0)
    created_at: datetime = Field(default_factory=utcnow)


class PrereqDagVersion(SQLModel, table=True):
    """Prerequisite DAG version."""

    __tablename__ = "prereq_dag_version"
    __table_args__ = (
        UniqueConstraint("subject", "version_no", name="uq_prereq_dag_subject_version"),
    )

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    version_no: int
    status: str = Field(default="draft")
    created_at: datetime = Field(default_factory=utcnow)


class UnitDependency(SQLModel, table=True):
    """Dependency edge between teaching units."""

    __tablename__ = "unit_dependency"
    __table_args__ = (
        UniqueConstraint(
            "dag_version_id",
            "source_unit_id",
            "target_unit_id",
            "dependency_type",
            name="uq_dag_dep",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    dag_version_id: int = Field(foreign_key="prereq_dag_version.id", index=True)
    source_unit_id: int = Field(foreign_key="teaching_unit.id", index=True)
    target_unit_id: int = Field(foreign_key="teaching_unit.id", index=True)
    dependency_type: str = Field(default="prerequisite")
    confidence: float = Field(default=0.5)
    supporting_edge_count: int = Field(default=0)
    derivation_metadata_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=utcnow)


class CurriculumSnapshot(SQLModel, table=True):
    """Published curriculum version / snapshot."""

    __tablename__ = "curriculum_version"
    __table_args__ = (
        UniqueConstraint("subject", "version_no", name="uq_curriculum_snapshot_subject_version"),
    )

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    version_no: int
    status: str = Field(default="draft")
    theme_tree_version_id: int | None = Field(default=None, foreign_key="theme_tree_version.id")
    prereq_dag_version_id: int | None = Field(default=None, foreign_key="prereq_dag_version.id")
    syllabus_version_id: int | None = Field(default=None)
    summary: str = ""
    blueprint_json: str = Field(default="{}")
    tree_json: str = Field(default="{}")
    dependency_json: str = Field(default="{}")
    build_context_json: str = Field(default="{}")
    is_current: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    published_at: datetime | None = Field(default=None)
    superseded_at: datetime | None = Field(default=None)


CurriculumVersion = CurriculumSnapshot
