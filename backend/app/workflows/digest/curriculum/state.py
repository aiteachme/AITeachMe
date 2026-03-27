"""Digest curriculum workflow state types."""

from __future__ import annotations

from typing import TypedDict

from app.workflows.digest.kg.services.impact_analyzer import ImpactSet


class CurriculumDeriveState(TypedDict, total=False):
    subject: str
    graph_job_id: int
    curriculum_job_id: int
    impact_set: ImpactSet | None
    derived_unit_ids: list[int]
    created_unit_ids: list[int]
    updated_unit_ids: list[int]
    theme_tree_version_id: int | None
    prereq_dag_version_id: int | None
    snapshot_id: int | None
    error: str | None


__all__ = ["CurriculumDeriveState"]
