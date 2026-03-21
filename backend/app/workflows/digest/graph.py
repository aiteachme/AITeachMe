"""Digest workflow graph entrypoints."""

from __future__ import annotations

from langgraph.graph import StateGraph

from app.agents.digest.curriculum_workflow import (
    _route_after_step as _route_after_curriculum_step,
    derive_prereq_dag_node,
    derive_theme_tree_node,
    derive_units_node,
    fail_curriculum_node,
    finalize_curriculum_node,
)
from app.agents.digest.kg_workflow import (
    _route_after_lock,
    _route_after_prepare,
    _route_after_step as _route_after_kg_step,
    acquire_lock_node,
    analyze_impact_node,
    cluster_node,
    extract_node,
    fail_node,
    finalize_graph_node,
    prepare_node,
    resolve_edges_node,
    resolve_nodes_node,
)
from app.workflows.common.context import WorkflowContext
from app.workflows.common.events import InProcessEventBus
from app.workflows.common.result import WorkflowResult, err_result
from app.workflows.common.runtime import run_state_graph
from app.workflows.common.state_graph_builder import build_state_graph_from_topology
from app.workflows.digest.diagrams import (
    CURRICULUM_DERIVE_DIAGRAM,
    KG_DIGEST_DIAGRAM,
    WORKFLOW_DIAGRAMS,
)
from app.workflows.digest.events import (
    CurriculumDeriveCompletedEvent,
    CurriculumDeriveFailedEvent,
    DigestBuildRequestedEvent,
    DigestGraphCompletedEvent,
    DigestGraphFailedEvent,
)
from app.workflows.digest.state import CurriculumDeriveState, KGDigestState

_KG_DIGEST_NODE_MAP = {
    "acquire_lock": acquire_lock_node,
    "prepare": prepare_node,
    "extract": extract_node,
    "cluster": cluster_node,
    "resolve_nodes": resolve_nodes_node,
    "resolve_edges": resolve_edges_node,
    "analyze_impact": analyze_impact_node,
    "finalize_graph": finalize_graph_node,
    "fail": fail_node,
}

_KG_DIGEST_ROUTE_MAP = {
    "acquire_lock": _route_after_lock,
    "prepare": _route_after_prepare,
    "extract": _route_after_kg_step,
    "cluster": _route_after_kg_step,
    "resolve_nodes": _route_after_kg_step,
    "resolve_edges": _route_after_kg_step,
    "analyze_impact": _route_after_kg_step,
}

_CURRICULUM_NODE_MAP = {
    "derive_units": derive_units_node,
    "derive_theme_tree": derive_theme_tree_node,
    "derive_prereq_dag": derive_prereq_dag_node,
    "finalize_curriculum": finalize_curriculum_node,
    "fail_curriculum": fail_curriculum_node,
}

_CURRICULUM_ROUTE_MAP = {
    "derive_units": _route_after_curriculum_step,
    "derive_theme_tree": _route_after_curriculum_step,
    "derive_prereq_dag": _route_after_curriculum_step,
}


def build_kg_digest_graph() -> StateGraph:
    """Build the digest graph StateGraph inside workflows/."""

    return build_state_graph_from_topology(
        state_type=KGDigestState,
        node_map=_KG_DIGEST_NODE_MAP,
        route_map=_KG_DIGEST_ROUTE_MAP,
        spec=KG_DIGEST_DIAGRAM,
    )


def build_curriculum_derive_graph() -> StateGraph:
    """Build the curriculum derive StateGraph inside workflows/."""

    return build_state_graph_from_topology(
        state_type=CurriculumDeriveState,
        node_map=_CURRICULUM_NODE_MAP,
        route_map=_CURRICULUM_ROUTE_MAP,
        spec=CURRICULUM_DERIVE_DIAGRAM,
    )


def create_graph_digest_initial_state(
    *,
    subject: str,
    file_ids: list[int],
    job_id: int,
) -> KGDigestState:
    """Create the initial state for digest graph building."""

    return {
        "subject": subject,
        "file_ids": file_ids,
        "job_id": job_id,
        "chunk_ids": [],
        "candidates": [],
        "all_candidate_edges": [],
        "clustered_candidates": [],
        "candidate_name_to_cluster_id": {},
        "candidate_name_to_resolved_node_id": {},
        "cluster_id_to_resolved_node_id": {},
        "new_node_ids": [],
        "updated_node_ids": [],
        "merged_node_ids": [],
        "new_edge_ids": [],
        "updated_edge_ids": [],
        "impact_set": None,
        "lock_acquired": False,
        "error": None,
    }


def create_curriculum_derive_initial_state(
    *,
    subject: str,
    graph_job_id: int,
    curriculum_job_id: int,
) -> CurriculumDeriveState:
    """Create the initial state for curriculum derive."""

    return {
        "subject": subject,
        "graph_job_id": graph_job_id,
        "curriculum_job_id": curriculum_job_id,
        "impact_set": None,
        "derived_unit_ids": [],
        "theme_tree_version_id": None,
        "prereq_dag_version_id": None,
        "snapshot_id": None,
        "error": None,
    }


async def run_graph_digest_workflow(
    *,
    subject: str,
    job_id: int,
    file_ids: list[int],
    event_bus: InProcessEventBus | None = None,
) -> WorkflowResult[KGDigestState]:
    """Run the digest graph workflow."""

    bus = event_bus or InProcessEventBus()
    await bus.publish(DigestBuildRequestedEvent(subject=subject, job_id=job_id, file_ids=file_ids))
    context = WorkflowContext(
        workflow_name="digest.graph",
        subject=subject,
        event_bus=bus,
        metadata={"job_id": job_id},
    )
    result = await run_state_graph(
        workflow_name="digest.graph",
        graph_builder=build_kg_digest_graph,
        initial_state=create_graph_digest_initial_state(subject=subject, file_ids=file_ids, job_id=job_id),
        context=context,
    )
    if result.failed:
        await bus.publish(
            DigestGraphFailedEvent(
                subject=subject,
                job_id=job_id,
                file_ids=file_ids,
                error_message=result.error.detail,
            )
        )
        return result

    final_state = result.require_value()
    error_message = final_state.get("error")
    if error_message:
        await bus.publish(
            DigestGraphFailedEvent(
                subject=subject,
                job_id=job_id,
                file_ids=file_ids,
                error_message=error_message,
            )
        )
        return err_result(
            "digest_graph_failed",
            error_message,
            metadata={"job_id": job_id, "subject": subject},
        )

    await bus.publish(
        DigestGraphCompletedEvent(
            subject=subject,
            job_id=job_id,
            file_ids=file_ids,
            chunk_count=len(final_state.get("chunk_ids", [])),
        )
    )
    return result


async def run_curriculum_derive_workflow(
    *,
    subject: str,
    graph_job_id: int,
    curriculum_job_id: int,
    event_bus: InProcessEventBus | None = None,
) -> WorkflowResult[CurriculumDeriveState]:
    """Run the digest curriculum workflow."""

    bus = event_bus or InProcessEventBus()
    context = WorkflowContext(
        workflow_name="digest.curriculum",
        subject=subject,
        event_bus=bus,
        metadata={"graph_job_id": graph_job_id, "curriculum_job_id": curriculum_job_id},
    )
    result = await run_state_graph(
        workflow_name="digest.curriculum",
        graph_builder=build_curriculum_derive_graph,
        initial_state=create_curriculum_derive_initial_state(
            subject=subject,
            graph_job_id=graph_job_id,
            curriculum_job_id=curriculum_job_id,
        ),
        context=context,
    )
    if result.failed:
        await bus.publish(
            CurriculumDeriveFailedEvent(
                subject=subject,
                graph_job_id=graph_job_id,
                curriculum_job_id=curriculum_job_id,
                error_message=result.error.detail,
            )
        )
        return result

    final_state = result.require_value()
    error_message = final_state.get("error")
    if error_message:
        await bus.publish(
            CurriculumDeriveFailedEvent(
                subject=subject,
                graph_job_id=graph_job_id,
                curriculum_job_id=curriculum_job_id,
                error_message=error_message,
            )
        )
        return err_result(
            "digest_curriculum_failed",
            error_message,
            metadata={"graph_job_id": graph_job_id, "curriculum_job_id": curriculum_job_id},
        )

    await bus.publish(
        CurriculumDeriveCompletedEvent(
            subject=subject,
            graph_job_id=graph_job_id,
            curriculum_job_id=curriculum_job_id,
        )
    )
    return result
