"""Workflow export definitions for examine lanes."""

from __future__ import annotations

from app.shared.infra.workflow.graph_export import WorkflowGraphExport
from app.workflows.examine.exam_grade.graph import (
    NODE_DISPLAY_NAMES as EXAM_GRADE_NODE_DISPLAY_NAMES,
    get_langgraph_dev_exam_grade_graph,
)
from app.workflows.examine.question_build.graph import (
    NODE_DISPLAY_NAMES as QUESTION_BUILD_NODE_DISPLAY_NAMES,
    get_langgraph_dev_question_build_graph,
)

QUESTION_BUILD_PROMPTS = {
    "knowledge_unit_filter_prompt": "Exam question-build knowledge-unit filter prompt.",
    "question_requirement_prompt": "Exam question type and requirement planning prompt.",
    "question_blueprint_prompt": "Exam knowledge-unit allocation blueprint prompt.",
    "question_generation_prompt": "Structured exam question generation prompt.",
}

EXAM_GRADE_PROMPTS = {
    "objective_feedback_prompt": "Objective-question feedback prompt.",
    "subjective_grade_prompt": "Subjective-question grading prompt.",
    "study_guide_prompt": "Post-exam study guide prompt.",
}

WORKFLOW_EXPORTS = (
    WorkflowGraphExport(
        key="examine_question_build",
        title="Examine Question Build Workflow",
        description="Exam question generation workflow from candidate knowledge units to structured questions.",
        build_graph=get_langgraph_dev_question_build_graph,
        node_labels=QUESTION_BUILD_NODE_DISPLAY_NAMES,
        prompts=QUESTION_BUILD_PROMPTS,
    ),
    WorkflowGraphExport(
        key="examine_exam_grade",
        title="Examine Exam Grade Workflow",
        description="Exam grading workflow that routes to paper grading or post-exam study-guide generation.",
        build_graph=get_langgraph_dev_exam_grade_graph,
        node_labels=EXAM_GRADE_NODE_DISPLAY_NAMES,
        prompts=EXAM_GRADE_PROMPTS,
    ),
)


__all__ = ["WORKFLOW_EXPORTS"]
