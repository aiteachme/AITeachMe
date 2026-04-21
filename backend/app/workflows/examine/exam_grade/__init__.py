"""Stable exports for the examine exam-grade lane."""

from app.workflows.examine.exam_grade.graph import build_exam_grade_graph

__all__ = ["build_exam_grade_graph"]
