from __future__ import annotations

from app.models.knowledge_taxonomy import (
    normalize_knowledge_unit_type,
    normalize_relation_type,
    validate_relation_direction,
)


def test_knowledge_unit_type_normalizes_only_p1_standard_values() -> None:
    assert normalize_knowledge_unit_type("concept") == "concept"
    assert normalize_knowledge_unit_type("definition") == "definition"
    assert normalize_knowledge_unit_type("method") == "method"
    assert normalize_knowledge_unit_type("example") == "example"
    assert normalize_knowledge_unit_type("proof_step") == "proof_step"
    assert normalize_knowledge_unit_type("unknown") == "concept"


def test_relation_type_normalizes_only_p1_standard_values() -> None:
    assert normalize_relation_type("prerequisite") == "prerequisite"
    assert normalize_relation_type("derivation") == "derivation"
    assert normalize_relation_type("application") == "application"
    assert normalize_relation_type("example_of") == "example_of"
    assert normalize_relation_type("unknown") == "application"


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

