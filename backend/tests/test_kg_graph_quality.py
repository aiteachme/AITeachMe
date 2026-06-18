from app.workflows.digest.common.markdown_knowledge_anchors import MarkdownKnowledgeUnit
from app.workflows.digest.kg_doc_sync.lib.models import KnowledgeSyncExtractionPayload, MarkdownExtractedEdge
from app.workflows.digest.kg_doc_sync.lib.quality import audit_knowledge_sync_payload
from app.workflows.digest.kg_doc_sync.nodes.audit_node import audit_node


def _unit(anchor: str, name: str, *, unit_type: str = "concept", chapter_index: int = 1) -> MarkdownKnowledgeUnit:
    return MarkdownKnowledgeUnit(
        anchor=anchor,
        name=name,
        knowledge_unit_type=unit_type,
        chapter_index=chapter_index,
        body_markdown=f"{name} body",
    )


def _payload(
    units: list[MarkdownKnowledgeUnit],
    edges: list[MarkdownExtractedEdge],
) -> KnowledgeSyncExtractionPayload:
    return KnowledgeSyncExtractionPayload(
        units=units,
        extracted_edges=edges,
        diagnostics_totals={"chapter_count": 2},
    )


def test_graph_quality_audit_records_taxonomy_direction_endpoint_and_coverage_metrics() -> None:
    payload = audit_knowledge_sync_payload(
        _payload(
            [
                _unit("ku_concept", "函数", unit_type="concept", chapter_index=1),
                _unit("ku_topic", "总览", unit_type="topic", chapter_index=1),
                _unit("ku_bad", "旧类型", unit_type="legacy_kind", chapter_index=1),
            ],
            [
                MarkdownExtractedEdge("ku_concept", "ku_missing", "explains", "missing endpoint"),
                MarkdownExtractedEdge("ku_concept", "ku_topic", "prerequisite_for", "bad direction"),
                MarkdownExtractedEdge("ku_topic", "ku_concept", "legacy_relation", "bad type"),
            ],
        ),
        structured_context={
            "docgen_manifest": {
                "chapters_enhanced": [
                    {"chapter_index": 1, "title": "函数"},
                    {"chapter_index": 2, "title": "导数"},
                ]
            }
        },
    )
    diagnostics = payload.diagnostics_totals

    assert diagnostics["graph_audit_unit_count"] == 3
    assert diagnostics["graph_audit_edge_count"] == 3
    assert diagnostics["graph_audit_downstream_unit_count"] == 1
    assert diagnostics["graph_audit_exam_ready_unit_count"] == 1
    assert diagnostics["graph_audit_profile_ready_unit_count"] == 1
    assert diagnostics["graph_audit_diagnostic_unit_count"] == 0
    assert diagnostics["graph_audit_valid_relation_edge_count"] == 0
    assert diagnostics["graph_audit_structure_edge_count"] == 0
    assert diagnostics["graph_audit_exam_edge_count"] == 0
    assert diagnostics["graph_audit_examine_profile_ready"] == 0
    assert diagnostics["graph_audit_missing_chapter_count"] == 1
    assert diagnostics["graph_audit_chapter_coverage_pct"] == 50.0
    assert diagnostics["graph_audit_nonstandard_unit_type_count"] == 1
    assert diagnostics["graph_audit_nonstandard_edge_type_count"] == 1
    assert diagnostics["graph_audit_edge_endpoint_issue_count"] == 1
    assert diagnostics["graph_audit_relation_direction_issue_count"] == 1
    assert diagnostics["graph_audit_warning_count"] == 5


def test_audit_node_updates_payload_and_node_metrics() -> None:
    result = audit_node(
        {
            "structured_context": {"chapters": [{"chapter_index": 1}]},
            "extraction_payload": _payload(
                [_unit("ku_concept", "函数", unit_type="concept", chapter_index=1)],
                [],
            ),
            "node_metrics": {},
        }
    )

    assert result["error"] is None
    assert result["node_metrics"]["audit_graph"]["ok"] is True
    assert result["node_metrics"]["audit_graph"]["chapter_coverage_pct"] == 100.0
    assert result["node_metrics"]["audit_graph"]["exam_ready_unit_count"] == 1
    assert result["node_metrics"]["audit_graph"]["profile_ready_unit_count"] == 1
    assert result["node_metrics"]["audit_graph"]["diagnostic_unit_count"] == 0
    assert result["node_metrics"]["audit_graph"]["examine_profile_ready"] == 0
    assert result["extraction_payload"].diagnostics_totals["graph_audit_warning_count"] == 0
