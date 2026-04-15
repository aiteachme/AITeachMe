"""Workflow graph exports for examine workflows."""

from __future__ import annotations

from app.shared.infra.workflow.graph_export import WorkflowGraphExport
from app.workflows.examine.graph import (
    build_exam_grade_graph,
    build_examine_workflow_graph,
    build_question_build_graph,
)
from app.workflows.examine.prompts.prompts import PROMPTS

WORKFLOW_EXPORTS = (
    WorkflowGraphExport(
        key="examine_question_build",
        title="Examine Question Build Workflow",
        description="Question template build workflow driven by teaching-unit validation and template generation.",
        build_graph=build_question_build_graph,
        prompts=PROMPTS,
    ),
    WorkflowGraphExport(
        key="examine_exam_grade",
        title="Examine Exam Grade Workflow",
        description="Exam grading workflow including grading, mastery update, and review scheduling.",
        build_graph=build_exam_grade_graph,
        prompts=PROMPTS,
    ),
    WorkflowGraphExport(
        key="examine_flow",
        title="Examine Workflow",
        description="High-level examine workflow from question-template build to grading and review scheduling.",
        build_graph=build_examine_workflow_graph,
        prompts=PROMPTS,
    ),
)


