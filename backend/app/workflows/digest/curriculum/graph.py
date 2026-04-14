"""Digest curriculum workflow graph and initial state."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.shared.infra.workflow import workflow_tracer
from app.workflows.digest.curriculum.nodes import (
    derive_prereq_dag_node,
    derive_theme_tree_node,
    derive_units_node,
    fail_curriculum_node,
    finalize_curriculum_node,
    route_after_step,
)
from app.workflows.digest.curriculum.state import CurriculumDeriveState
from app.workflows.digest.kg.services.impact_analyzer import ImpactSet


def build_curriculum_derive_graph() -> StateGraph:
    """Build the LangGraph workflow for curriculum derivation."""

    workflow = StateGraph(CurriculumDeriveState)
    trace = workflow_tracer(workflow="digest.curriculum", lane="curriculum")
    workflow.add_node(
        "derive_units",
        trace.node(
            derive_units_node,
            name="derive_units",
            timing_field="derive_units_ms",
        ),
    )
    workflow.add_node(
        "derive_theme_tree",
        trace.node(
            derive_theme_tree_node,
            name="derive_theme_tree",
            timing_field="theme_tree_ms",
        ),
    )
    workflow.add_node(
        "derive_prereq_dag",
        trace.node(
            derive_prereq_dag_node,
            name="derive_prereq_dag",
            timing_field="prereq_dag_ms",
        ),
    )
    workflow.add_node(
        "finalize_curriculum",
        trace.node(
            finalize_curriculum_node,
            name="finalize_curriculum",
            timing_field="finalize_ms",
        ),
    )
    workflow.add_node(
        "fail_curriculum",
        trace.node(
            fail_curriculum_node,
            name="fail_curriculum",
        ),
    )

    workflow.set_entry_point("derive_units")
    workflow.add_conditional_edges(
        "derive_units",
        route_after_step,
        {
            "continue": "derive_theme_tree",
            "fail": "fail_curriculum",
        },
    )
    workflow.add_conditional_edges(
        "derive_theme_tree",
        route_after_step,
        {
            "continue": "derive_prereq_dag",
            "fail": "fail_curriculum",
        },
    )
    workflow.add_conditional_edges(
        "derive_prereq_dag",
        route_after_step,
        {
            "continue": "finalize_curriculum",
            "fail": "fail_curriculum",
        },
    )
    workflow.add_edge("finalize_curriculum", END)
    workflow.add_edge("fail_curriculum", END)
    return workflow

def create_curriculum_derive_initial_state(
    *,
    subject: str,
    graph_job_id: int,
    curriculum_job_id: int,
    impact_set: ImpactSet | None = None,
    build_session_id: str | None = None,
) -> CurriculumDeriveState:
    """Create the initial state for curriculum derivation."""

    return {
        "subject": subject,
        "build_session_id": build_session_id or "",
        "graph_job_id": graph_job_id,
        "curriculum_job_id": curriculum_job_id,
        "impact_set": impact_set,
        "derived_unit_ids": [],
        "theme_tree_version_id": None,
        "prereq_dag_version_id": None,
        "snapshot_id": None,
        "curriculum_version_no": None,
        "error": None,
    }


__all__ = [
    "build_curriculum_derive_graph",
    "create_curriculum_derive_initial_state",
]

