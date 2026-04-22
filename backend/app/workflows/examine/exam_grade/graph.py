"""Stable workflow exports for the exam-grade lane."""

from __future__ import annotations

from typing import TypedDict

from app.models import ExamPaperItem
from app.workflows.examine.exam_grade.lib import grade_exam_items_with_workflow
from langgraph.graph import END, StateGraph


class ExamGradeState(TypedDict, total=False):
    exam_paper_id: int
    status: str


def build_exam_grade_graph() -> StateGraph:
    workflow = StateGraph(ExamGradeState)
    workflow.add_node("grade_exam", _grade_exam_node)
    workflow.set_entry_point("grade_exam")
    workflow.add_edge("grade_exam", END)
    return workflow


def _grade_exam_node(state: ExamGradeState) -> ExamGradeState:
    return {
        **state,
        "status": str(state.get("status") or "ready"),
    }

async def run_exam_grade_workflow(
    *,
    subject: str,
    items: list[ExamPaperItem],
):
    """Run the production exam grading workflow."""

    return await grade_exam_items_with_workflow(subject=subject, items=items)


__all__ = ["ExamGradeState", "build_exam_grade_graph", "run_exam_grade_workflow"]
