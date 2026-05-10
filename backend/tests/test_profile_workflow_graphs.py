"""Profile workflow graph structure smoke tests."""

from app.workflows.profile import WORKFLOW_EXPORTS
from app.workflows.profile.snapshot import build_profile_snapshot_graph
from app.workflows.profile.study_plan import build_profile_study_plan_graph
from app.workflows.profile.update import build_profile_update_graph


def _assert_node_descriptions(graph) -> None:
    missing = [
        node_name
        for node_name, node_spec in graph.nodes.items()
        if not str((getattr(node_spec, "metadata", {}) or {}).get("node_description") or "").strip()
    ]

    assert missing == []


def test_profile_workflow_graphs_compile_and_export() -> None:
    update_graph = build_profile_update_graph()
    snapshot_graph = build_profile_snapshot_graph()
    study_plan_graph = build_profile_study_plan_graph()

    update_graph.compile()
    snapshot_graph.compile()
    study_plan_graph.compile()

    _assert_node_descriptions(update_graph)
    _assert_node_descriptions(snapshot_graph)
    _assert_node_descriptions(study_plan_graph)

    export_keys = {item.key for item in WORKFLOW_EXPORTS}

    assert "profile_update" in export_keys
    assert "profile_snapshot" in export_keys
    assert "profile_study_plan" in export_keys
