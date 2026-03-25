"""Curriculum structure models."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, Index, SQLModel, UniqueConstraint

from app.utils.time import utcnow


class TeachingUnit(SQLModel, table=True):
    """Teaching unit as the main curriculum atom."""

    __tablename__ = "teaching_unit"
    __table_args__ = (
        UniqueConstraint("subject_id", "member_signature", name="uq_teaching_unit_signature"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    subject_id: int = Field(foreign_key="subject.id", index=True)
    canonical_name: str
    normalized_name: str = Field(index=True)
    member_signature: str = Field(index=True)
    summary: str = Field(default="")
    learning_objectives_json: str = Field(default="[]")
    status: str = Field(default="active", index=True)
    confidence: float = Field(default=1.0)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class TeachingUnitMembership(SQLModel, table=True):
    """Knowledge node membership in a teaching unit."""

    __tablename__ = "teaching_unit_membership"
    __table_args__ = (
        UniqueConstraint(
            "unit_id",
            "knowledge_node_id",
            "role",
            name="uq_teaching_unit_membership",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    unit_id: int = Field(foreign_key="teaching_unit.id", index=True)
    knowledge_node_id: int = Field(foreign_key="knowledge_node.id", index=True)
    role: str = Field(default="core")
    score: float = Field(default=0.0)
    created_at: datetime = Field(default_factory=utcnow)


class CurriculumVersion(SQLModel, table=True):
    """Published or draft curriculum snapshot root."""

    __tablename__ = "curriculum_version"
    __table_args__ = (
        UniqueConstraint("subject_id", "version_no", name="uq_curriculum_version_no"),
        Index("ix_curriculum_version_subject_status", "subject_id", "status"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    subject_id: int = Field(foreign_key="subject.id", index=True)
    version_no: int = Field(ge=1)
    status: str = Field(default="draft", index=True)
    summary: str = Field(default="")
    metadata_json: str = Field(default="{}")
    published_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class CurriculumTreeNode(SQLModel, table=True):
    """Curriculum tree node merging theme tree and anchor semantics."""

    __tablename__ = "curriculum_tree_node"
    __table_args__ = (
        Index("ix_curriculum_tree_parent_order", "curriculum_version_id", "parent_tree_node_id", "order_index"),
    )

    id: int | None = Field(default=None, primary_key=True)
    curriculum_version_id: int = Field(foreign_key="curriculum_version.id", index=True)
    parent_tree_node_id: int | None = Field(default=None, foreign_key="curriculum_tree_node.id", index=True)
    title: str
    normalized_title: str = Field(index=True)
    node_type: str = Field(default="theme", index=True)
    anchor_type: str = Field(default="system", index=True)
    confidence: float = Field(default=1.0)
    is_system: bool = Field(default=False)
    order_index: int = Field(default=0)
    summary: str = Field(default="")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class CurriculumUnitLink(SQLModel, table=True):
    """Teaching unit mounted onto a curriculum tree node."""

    __tablename__ = "curriculum_unit_link"
    __table_args__ = (
        UniqueConstraint(
            "curriculum_version_id",
            "tree_node_id",
            "teaching_unit_id",
            "membership_role",
            name="uq_curriculum_unit_link",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    curriculum_version_id: int = Field(foreign_key="curriculum_version.id", index=True)
    tree_node_id: int = Field(foreign_key="curriculum_tree_node.id", index=True)
    teaching_unit_id: int = Field(foreign_key="teaching_unit.id", index=True)
    membership_role: str = Field(default="primary")
    membership_source: str = Field(default="auto")
    score: float = Field(default=0.0)
    created_at: datetime = Field(default_factory=utcnow)


class CurriculumDependency(SQLModel, table=True):
    """Prerequisite or co-requisite dependency within one curriculum version."""

    __tablename__ = "curriculum_dependency"
    __table_args__ = (
        UniqueConstraint(
            "curriculum_version_id",
            "source_unit_id",
            "target_unit_id",
            "dependency_type",
            name="uq_curriculum_dependency",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    curriculum_version_id: int = Field(foreign_key="curriculum_version.id", index=True)
    source_unit_id: int = Field(foreign_key="teaching_unit.id", index=True)
    target_unit_id: int = Field(foreign_key="teaching_unit.id", index=True)
    dependency_type: str = Field(default="prerequisite")
    confidence: float = Field(default=0.5)
    supporting_edge_count: int = Field(default=0, ge=0)
    derivation_metadata_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=utcnow)
