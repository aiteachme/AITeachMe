"""Minimal LangGraph export for the exam-grade lane.

The production grading flow is still invoked through the exams API. This graph
exists so LangGraph dev/export references for the examine engine remain valid.
"""

from __future__ import annotations

from typing import TypedDict

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


__all__ = ["ExamGradeState", "build_exam_grade_graph"]
