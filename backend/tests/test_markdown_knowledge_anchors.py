from __future__ import annotations

import pytest

from app.workflows.digest.knowledge_graph.lib.extractor import extract_candidates
from app.workflows.digest.common.markdown_knowledge_anchors import (
    ensure_markdown_knowledge_unit_anchors,
    extract_markdown_knowledge_units,
    validate_knowledge_unit_anchors,
)


def test_ensure_markdown_knowledge_unit_anchors_adds_stable_heading_anchor() -> None:
    markdown = "# Linear Functions\n\nDefinition: slope is rate of change.\n"

    anchored = ensure_markdown_knowledge_unit_anchors(markdown)

    assert "# Linear Functions {#ku_linear-functions}" in anchored
    assert "Definition: slope is rate of change. {#ku_definition-slope-is-rate-of-change}" in anchored
    assert validate_knowledge_unit_anchors(anchored).ok


def test_validate_knowledge_unit_anchors_reports_duplicates_and_invalid_prefixes() -> None:
    markdown = "# A {#ku_a}\n\n# B {#ku_a}\n\n# C {#bad_anchor}\n"

    result = validate_knowledge_unit_anchors(markdown)

    assert not result.ok
    assert result.duplicate_anchors == ["ku_a"]
    assert result.invalid_anchors == ["bad_anchor"]


def test_extract_markdown_knowledge_units_reads_tags() -> None:
    markdown = (
        "## Linear Function Definition {#ku_linear_function_definition} "
        "[type: definition] [prerequisite: Function] [related: Slope]\n"
        "A linear function has constant rate of change.\n"
    )

    units = extract_markdown_knowledge_units(markdown)

    assert len(units) == 1
    assert units[0].anchor == "ku_linear_function_definition"
    assert units[0].name == "Linear Function Definition"
    assert units[0].knowledge_unit_type == "definition"
    assert units[0].prerequisites == ["Function"]
    assert units[0].related == ["Slope"]


@pytest.mark.asyncio
async def test_extract_candidates_prefers_markdown_knowledge_unit_anchors() -> None:
    result = await extract_candidates(
        (
            "## Linear Function Definition {#ku_linear_function_definition} "
            "[type: definition] [prerequisite: Function]\n"
            "A linear function has constant rate of change.\n"
        ),
        chunk_title="Linear Functions",
        header_path="Algebra > Linear Functions",
    )

    names = {node.name: node for node in result.nodes}
    assert names["Linear Function Definition"].candidate_id == "ku_linear_function_definition"
    assert names["Linear Function Definition"].anchor_id == "ku_linear_function_definition"
    assert names["Linear Function Definition"].knowledge_unit_type == "definition"
    assert "Function" in names
    assert any(
        edge.edge_type == "prerequisite"
        and edge.source_name == "Function"
        and edge.target_name == "Linear Function Definition"
        for edge in result.edges
    )
