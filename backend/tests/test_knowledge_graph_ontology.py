from app.models.enums import KnowledgeRelationType, KnowledgeUnitType
from app.workflows.digest.kg_doc_sync.lib.ontology import (
    LEARNING_GRAPH_ONTOLOGY,
    format_ontology_relation_type_bullets,
    format_ontology_unit_type_bullets,
)
from app.models.knowledge_taxonomy import (
    PARENT_KNOWLEDGE_UNIT_TYPES,
    PRIMARY_KNOWLEDGE_UNIT_TYPES,
    SECONDARY_KNOWLEDGE_UNIT_TYPES,
    STANDARD_KNOWLEDGE_UNIT_TYPES,
    STANDARD_RELATION_TYPES,
    validate_relation_direction,
)
from app.workflows.digest.kg_doc_sync.prompts.section_graph import SYSTEM_PROMPT_KNOWLEDGE_EXTRACT


def test_learning_graph_ontology_matches_enum_values():
    assert STANDARD_KNOWLEDGE_UNIT_TYPES == {item.value for item in KnowledgeUnitType}
    assert STANDARD_RELATION_TYPES == {item.value for item in KnowledgeRelationType}
    assert PRIMARY_KNOWLEDGE_UNIT_TYPES | SECONDARY_KNOWLEDGE_UNIT_TYPES == STANDARD_KNOWLEDGE_UNIT_TYPES
    assert PRIMARY_KNOWLEDGE_UNIT_TYPES.isdisjoint(SECONDARY_KNOWLEDGE_UNIT_TYPES)
    assert PARENT_KNOWLEDGE_UNIT_TYPES == PRIMARY_KNOWLEDGE_UNIT_TYPES | {KnowledgeUnitType.DEFINITION.value}
    assert set(LEARNING_GRAPH_ONTOLOGY.unit_type_values) == STANDARD_KNOWLEDGE_UNIT_TYPES
    assert set(LEARNING_GRAPH_ONTOLOGY.relation_type_values) == STANDARD_RELATION_TYPES
    assert set(LEARNING_GRAPH_ONTOLOGY.primary_unit_type_values) == PRIMARY_KNOWLEDGE_UNIT_TYPES
    assert set(LEARNING_GRAPH_ONTOLOGY.secondary_unit_type_values) == SECONDARY_KNOWLEDGE_UNIT_TYPES
    assert set(LEARNING_GRAPH_ONTOLOGY.parent_unit_type_values) == PARENT_KNOWLEDGE_UNIT_TYPES


def test_section_graph_prompt_uses_canonical_ontology_bullets():
    unit_bullets = format_ontology_unit_type_bullets()
    relation_bullets = format_ontology_relation_type_bullets()

    assert unit_bullets in SYSTEM_PROMPT_KNOWLEDGE_EXTRACT
    assert relation_bullets in SYSTEM_PROMPT_KNOWLEDGE_EXTRACT
    for spec in LEARNING_GRAPH_ONTOLOGY.unit_types:
        assert f"`{spec.value}`" in SYSTEM_PROMPT_KNOWLEDGE_EXTRACT
    for spec in LEARNING_GRAPH_ONTOLOGY.relation_types:
        assert f"`{spec.value}`" in SYSTEM_PROMPT_KNOWLEDGE_EXTRACT


def test_relation_direction_rules_match_kg_doc_sync_ontology():
    assert validate_relation_direction(edge_type="example_of", source_type="example", target_type="concept")
    assert validate_relation_direction(edge_type="example_of", source_type="exercise", target_type="method")
    assert not validate_relation_direction(edge_type="example_of", source_type="concept", target_type="method")
    assert not validate_relation_direction(edge_type="prerequisite", source_type="example", target_type="concept")
    assert not validate_relation_direction(edge_type="prerequisite", source_type="concept", target_type="example")
    assert not validate_relation_direction(edge_type="similar", source_type="example", target_type="concept")
    assert not validate_relation_direction(edge_type="contrast", source_type="concept", target_type="example")
    for spec in LEARNING_GRAPH_ONTOLOGY.relation_types:
        assert spec.allows(source_type="concept", target_type="method") == validate_relation_direction(
            edge_type=spec.value,
            source_type="concept",
            target_type="method",
        )
