from app.workflows.digest.docgen import graph as docgen_graph
from app.shared.infra.workflow.context import WorkflowContext
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


def test_docgen_prepares_knowledge_graph_after_final_titles_before_publish() -> None:
    workflow = docgen_graph.build_docgen_graph(
        context=WorkflowContext(workflow_name="digest.docgen.test", course_id="course_graph_order")
    )

    def next_node(node_key: str) -> str:
        return workflow.branches[node_key]["检查是否继续"].ends["continue"]

    def fail_node(node_key: str) -> str:
        return workflow.branches[node_key]["检查是否继续"].ends["fail"]

    assert (
        (docgen_graph.NODE_REPAIR_OR_ROUTE, docgen_graph.NODE_GENERATE_COVER),
        docgen_graph.NODE_MERGE_REVIEW,
    ) in workflow.waiting_edges
    assert (
        (docgen_graph.NODE_PREPARE_GLOBAL_SEED, docgen_graph.NODE_LOCK_TITLES),
        docgen_graph.NODE_CONFIRM_BACKBONE_SEED,
    ) in workflow.waiting_edges
    assert next_node(docgen_graph.NODE_CONFIRM_BACKBONE_SEED) == docgen_graph.NODE_BUILD_DOCUMENT_BACKBONE
    assert (
        docgen_graph.NODE_BUILD_CHAPTER_BRIEF,
        docgen_graph.NODE_ASSEMBLE_CHAPTER_TASKS,
    ) in workflow.edges
    assert next_node(docgen_graph.NODE_MERGE_REVIEW) == docgen_graph.NODE_SYNC_LOCKED_TITLES
    assert next_node(docgen_graph.NODE_SYNC_LOCKED_TITLES) == docgen_graph.NODE_PREPARE_KNOWLEDGE_GRAPH
    assert next_node(docgen_graph.NODE_PREPARE_KNOWLEDGE_GRAPH) == docgen_graph.NODE_PUBLISH
    assert fail_node(docgen_graph.NODE_PREPARE_KNOWLEDGE_GRAPH) == docgen_graph.NODE_ROLLBACK_KNOWLEDGE_GRAPH
    assert fail_node(docgen_graph.NODE_PUBLISH) == docgen_graph.NODE_ROLLBACK_KNOWLEDGE_GRAPH
