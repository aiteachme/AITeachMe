from __future__ import annotations

from app.models.kg_taxonomy import (
    normalize_knowledge_unit_type,
    normalize_relation_type,
    validate_relation_direction,
)


def test_knowledge_unit_type_aliases_normalize_to_p1_standard_values() -> None:
    assert normalize_knowledge_unit_type("Topic") == "concept"
    assert normalize_knowledge_unit_type("Concept") == "concept"
    assert normalize_knowledge_unit_type("Definition") == "definition"
    assert normalize_knowledge_unit_type("Method") == "method"
    assert normalize_knowledge_unit_type("Example") == "example"
    assert normalize_knowledge_unit_type("proof-step") == "proof_step"
    assert normalize_knowledge_unit_type("unknown") == "concept"


def test_legacy_relation_aliases_normalize_to_p1_standard_values() -> None:
    assert normalize_relation_type("prerequisite_of").edge_type == "prerequisite"
    assert normalize_relation_type("defined_by").edge_type == "derivation"
    assert normalize_relation_type("defined_by").swap_endpoints is True
    assert normalize_relation_type("illustrated_by").edge_type == "example_of"
    assert normalize_relation_type("illustrated_by").swap_endpoints is True
    assert normalize_relation_type("belongs_to_topic").edge_type == "application"
    assert normalize_relation_type("part_of").edge_type == "derivation"


def test_relation_direction_constraints_for_examples_and_prerequisites() -> None:
    assert validate_relation_direction(
        edge_type="example_of",
        source_type="example",
        target_type="concept",
    )
    assert not validate_relation_direction(
        edge_type="example_of",
        source_type="concept",
        target_type="example",
    )
    assert not validate_relation_direction(
        edge_type="prerequisite",
        source_type="example",
        target_type="concept",
    )
