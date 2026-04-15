"""Compatibility wrapper exposing exam-grade helpers."""

from app.workflows.examine.answer_grader import grade_paper

__all__ = ["grade_paper"]
