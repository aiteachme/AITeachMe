from app.workflows.digest.docgen import graph as docgen_graph
from app.workflows.digest.kg_doc_sync import graph as kg_doc_sync_graph
from app.workflows.digest.planner import graph as planner_graph


def _assert_trace_details_complete(display_names: dict[str, str], trace_details: dict[str, dict]) -> None:
    assert set(display_names) == set(trace_details)
    for node_key, display_name in display_names.items():
        details = trace_details[node_key]
        assert display_name.strip()
        assert str(details.get("description") or "").strip()
        assert list(details.get("reads") or [])
        assert list(details.get("writes") or [])
        assert list(details.get("input_keys") or [])
        assert list(details.get("output_keys") or [])


def test_digest_workflow_nodes_have_langsmith_metadata() -> None:
    _assert_trace_details_complete(docgen_graph.NODE_DISPLAY_NAMES, docgen_graph.NODE_TRACE_DETAILS)
    _assert_trace_details_complete(kg_doc_sync_graph.NODE_DISPLAY_NAMES, kg_doc_sync_graph.NODE_TRACE_DETAILS)
    _assert_trace_details_complete(planner_graph.STEP_DISPLAY_NAMES, planner_graph.NODE_TRACE_DETAILS)
