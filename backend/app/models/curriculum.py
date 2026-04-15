"""Legacy curriculum snapshot models used by examine/profile workflows."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.utils.time import utcnow


class Curriculum(SQLModel, table=True):
    """Published curriculum snapshot metadata."""

    __tablename__ = "curriculum"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    version_no: int = Field(default=1, ge=1)
    status: str = Field(default="published", index=True)
    is_current: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


CurriculumSnapshot = Curriculum


class TeachingUnit(SQLModel, table=True):
    """Teaching unit used by legacy examine/profile scopes."""

    __tablename__ = "teaching_unit"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    canonical_name: str
    normalized_name: str = Field(default="", index=True)
    member_signature: str = Field(default="", index=True)
    summary: str = ""
    body_markdown: str = ""
    member_node_refs_json: str = Field(default="[]")
    learning_objectives_json: str = Field(default="[]")
    status: str = Field(default="active", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @property
    def title(self) -> str:
        """Backward-compatible display title."""

        return self.canonical_name


class ThemeTreeNode(SQLModel, table=True):
    """Theme tree node used to resolve teaching-unit scopes."""

    __tablename__ = "theme_tree_node"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    tree_version_id: int = Field(index=True)
    anchor_id: int | None = Field(default=None, index=True)
    parent_tree_node_id: int | None = Field(default=None, index=True)
    title: str
    node_type: str = Field(default="theme", index=True)
    unit_refs_json: str = Field(default="[]")
    order_index: int = Field(default=0)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class TaxonomyAnchor(SQLModel, table=True):
    """Legacy taxonomy anchor used by curriculum tree previews."""

    __tablename__ = "taxonomy_anchor"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    anchor_type: str = Field(index=True)
    title: str
    normalized_title: str = Field(default="", index=True)
    parent_anchor_id: int | None = Field(default=None, index=True)
    order_index: int = Field(default=0)
    status: str = Field(default="active", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class UnitDependency(SQLModel, table=True):
    """Directed dependency edge between teaching units."""

    __tablename__ = "unit_dependency"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    dag_version_id: int = Field(index=True)
    source_unit_id: int = Field(index=True)
    target_unit_id: int = Field(index=True)
    dependency_type: str = Field(default="prerequisite", index=True)
    weight: float = Field(default=1.0)
    created_at: datetime = Field(default_factory=utcnow)


__all__ = [
    "Curriculum",
    "CurriculumSnapshot",
    "TaxonomyAnchor",
    "TeachingUnit",
    "ThemeTreeNode",
    "UnitDependency",
]
