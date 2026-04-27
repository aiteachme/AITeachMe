from app.workflows.digest.kg_doc_sync.graph import create_docs_sync_initial_state, route_after_extract
from app.workflows.digest.kg_doc_sync.lib.incremental_sync import graph_extraction_parallelism
from app.workflows.digest.kg_doc_sync.lib.models import (
    KnowledgeSyncExtractionPayload,
    KnowledgeSyncRunContext,
)
import app.workflows.digest.kg_doc_sync.nodes.extract_node as extract_node_module
from app.workflows.digest.kg_doc_sync.nodes.extract_node import extract_node
from app.workflows.digest.kg_doc_sync.nodes.fail_node import fail_node
from app.workflows.digest.kg_doc_sync.nodes.finalize_node import finalize_node
from app.workflows.digest.kg_doc_sync.nodes.prepare_node import prepare_node


def test_create_initial_state_seeds_node_metrics():
    state = create_docs_sync_initial_state(
        subject="math",
        markdown="# Algebra",
        build_revision_no=None,
    )

    assert state["node_metrics"] == {}


def test_prepare_node_records_input_metrics():
    state = create_docs_sync_initial_state(
        subject=" math ",
        markdown="# Algebra\n\n<!-- atm-ku:abc -->\n\nBody",
        build_revision_no=None,
        structured_context={
            "doc_version_no": 3,
            "chapters": [{"chapter_index": 1}],
            "docgen_manifest": {"document_backbone_snapshot": {}},
            "document_summary_json": {"summary": "Algebra"},
        },
    )

    result = prepare_node(state)
    metrics = result["node_metrics"]["prepare"]

    assert result["subject"] == "math"
    assert result["error"] is None
    assert metrics["ok"] is True
    assert metrics["markdown_chars"] > 0
    assert metrics["heading_count"] == 1
    assert metrics["knowledge_anchor_count"] == 1
    assert metrics["doc_version_no"] == 3
    assert metrics["chapter_context_count"] == 1
    assert metrics["has_docgen_manifest"] is True
    assert metrics["has_document_summary"] is True


def test_extract_node_missing_run_context_records_parallelism_metrics():
    state = create_docs_sync_initial_state(
        subject="math",
        markdown="# Algebra",
        build_revision_no=None,
    )

    result = extract_node(state)
    metrics = result["node_metrics"]["extract"]
    parallelism = graph_extraction_parallelism()

    assert result["error"] == "docs_sync_run_context_missing"
    assert metrics["ok"] is False
    assert metrics["chapter_concurrency_limit"] == parallelism["chapter_concurrency_limit"]
    assert metrics["chapter_max_retries"] == parallelism["chapter_max_retries"]


def test_extract_route_fails_when_payload_is_missing():
    state = create_docs_sync_initial_state(
        subject="math",
        markdown="# Algebra",
        build_revision_no=None,
    )

    assert route_after_extract(state) == "fail"

    result = fail_node(state)
    metrics = result["node_metrics"]["fail"]

    assert result["error"] == "docs_sync_extraction_payload_missing"
    assert metrics["ok"] is False
    assert metrics["error"] == "docs_sync_extraction_payload_missing"
    assert metrics["reason"] == "sync_run_context_missing"


def test_extract_node_records_payload_and_routes_to_persist(monkeypatch):
    payload = KnowledgeSyncExtractionPayload(
        units=[],
        extracted_edges=[],
        diagnostics_totals={"chapter_count": 1, "section_count": 1},
    )

    def fake_extract_knowledge_graph_items(**kwargs):
        return payload

    monkeypatch.setattr(
        extract_node_module,
        "extract_knowledge_graph_items",
        fake_extract_knowledge_graph_items,
    )
    state = create_docs_sync_initial_state(
        subject="math",
        markdown="# Algebra\n\nBody",
        build_revision_no=None,
        subject_context="Algebra context",
    )
    state["sync_run_context"] = KnowledgeSyncRunContext(
        subject="math",
        build_revision_no=1,
        sync_run_id=10,
        doc_version_no=2,
    )

    result = extract_node(state)
    metrics = result["node_metrics"]["extract"]

    assert result["error"] is None
    assert result["extraction_payload"] is payload
    assert route_after_extract(result) == "persist"
    assert metrics["ok"] is True
    assert metrics["chapter_count"] == 1
    assert metrics["section_count"] == 1


def test_fail_node_prefers_extract_metric_error_when_payload_missing():
    state = create_docs_sync_initial_state(
        subject="math",
        markdown="# Algebra",
        build_revision_no=None,
    )
    state["node_metrics"]["extract"] = {
        "ok": False,
        "error": "upstream_llm_error",
    }

    result = fail_node(state)

    assert result["error"] == "upstream_llm_error"
    assert result["node_metrics"]["fail"]["error"] == "upstream_llm_error"


def test_finalize_node_missing_report_records_error_metrics():
    state = create_docs_sync_initial_state(
        subject="math",
        markdown="# Algebra",
        build_revision_no=None,
    )

    result = finalize_node(state)
    metrics = result["node_metrics"]["finalize"]

    assert result["error"] == "docs_sync_report_missing"
    assert metrics["ok"] is False
    assert metrics["error"] == "docs_sync_report_missing"
