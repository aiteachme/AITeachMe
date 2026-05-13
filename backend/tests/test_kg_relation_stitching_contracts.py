from app.workflows.digest.common.markdown_knowledge_anchors import MarkdownKnowledgeUnit
from app.workflows.digest.kg_doc_sync.lib.models import KnowledgeSyncExtractionPayload, MarkdownExtractedEdge
from app.workflows.digest.kg_doc_sync.lib.relation_stitching import stitch_knowledge_graph_relations


def _unit(
    anchor: str,
    name: str,
    *,
    knowledge_unit_type: str = "core_knowledge",
    summary: str = "",
    body_markdown: str = "shared section body",
    line_no: int = 10,
    chapter_index: int = 1,
) -> MarkdownKnowledgeUnit:
    return MarkdownKnowledgeUnit(
        anchor=anchor,
        name=name,
        knowledge_unit_type=knowledge_unit_type,
        summary=summary,
        body_markdown=body_markdown,
        line_no=line_no,
        chapter_index=chapter_index,
        knowledge_document_id=101,
        source_file_ids=["file-a"],
    )


def _payload(
    units: list[MarkdownKnowledgeUnit],
    edges: list[MarkdownExtractedEdge] | None = None,
) -> KnowledgeSyncExtractionPayload:
    return KnowledgeSyncExtractionPayload(
        units=units,
        extracted_edges=list(edges or []),
        diagnostics_totals={"original": 1},
    )


def test_section_local_stitching_links_secondary_units_to_primary_parent() -> None:
    result = stitch_knowledge_graph_relations(
        _payload(
            [
                _unit("ku_matrix", "Matrix"),
                _unit("ku_svd", "SVD example", knowledge_unit_type="method_demo"),
                _unit("ku_drill", "Matrix drill", knowledge_unit_type="practice_assessment"),
            ]
        )
    )

    stitched = {
        (edge.source_anchor, edge.target_anchor, edge.edge_type, edge.source_kind)
        for edge in result.extracted_edges
    }
    assert stitched == {
        ("ku_matrix", "ku_svd", "application", "section_local_stitch"),
        ("ku_matrix", "ku_drill", "training", "section_local_stitch"),
    }
    assert result.diagnostics_totals["section_local_stitch_edge_count"] == 2
    assert result.diagnostics_totals["mention_stitch_edge_count"] == 0
    assert result.diagnostics_totals["graph_isolated_unit_count"] == 0
    assert result.diagnostics_totals["graph_component_count"] == 1


def test_mention_stitching_infers_prerequisite_and_training_directions() -> None:
    result = stitch_knowledge_graph_relations(
        _payload(
            [
                _unit("ku_matrix", "Matrix", body_markdown="matrix definition", line_no=1),
                _unit(
                    "ku_rank",
                    "Rank",
                    summary="需要先掌握 Matrix 再学习 Rank",
                    body_markdown="rank body",
                    line_no=2,
                ),
                _unit(
                    "ku_practice",
                    "Practice",
                    knowledge_unit_type="practice_assessment",
                    summary="利用 Matrix 完成训练",
                    body_markdown="practice body",
                    line_no=3,
                ),
            ]
        )
    )

    stitched = {
        (edge.source_anchor, edge.target_anchor, edge.edge_type, edge.source_kind)
        for edge in result.extracted_edges
    }
    assert ("ku_matrix", "ku_rank", "prerequisite", "mention_stitch") in stitched
    assert ("ku_matrix", "ku_practice", "training", "mention_stitch") in stitched
    assert result.diagnostics_totals["mention_stitch_edge_count"] == 2
    assert result.diagnostics_totals["graph_active_edge_count"] == 2
    assert result.diagnostics_totals["graph_largest_component_unit_count"] == 3


def test_existing_edges_are_preserved_and_prevent_duplicate_stitches() -> None:
    existing = MarkdownExtractedEdge(
        source_anchor="ku_matrix",
        target_anchor="ku_svd",
        edge_type="application",
        description="existing",
        source_kind="llm_relation",
    )

    result = stitch_knowledge_graph_relations(
        _payload(
            [
                _unit("ku_matrix", "Matrix"),
                _unit("ku_svd", "SVD example", knowledge_unit_type="method_demo"),
                _unit("ku_note", "Loose note", body_markdown="standalone", line_no=99),
            ],
            edges=[existing],
        )
    )

    assert result.extracted_edges[0] is existing
    assert [
        (edge.source_anchor, edge.target_anchor, edge.edge_type)
        for edge in result.extracted_edges
    ].count(("ku_matrix", "ku_svd", "application")) == 1
    assert result.diagnostics_totals["stitched_edge_count"] == 0
    assert result.diagnostics_totals["graph_isolated_unit_count"] == 1
    assert result.diagnostics_totals["graph_component_count"] == 2
    assert result.diagnostics_totals["graph_isolated_unit_pct"] == 33.33
