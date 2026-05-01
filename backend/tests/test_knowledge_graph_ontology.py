from app.models.enums import KnowledgeRelationType, KnowledgeUnitType
from app.workflows.digest.kg_doc_sync.lib.ontology import (
    LEARNING_GRAPH_ONTOLOGY,
    default_relation_for_unit_type,
    format_ontology_relation_direction_bullets,
    format_ontology_relation_type_bullets,
    format_ontology_unit_type_bullets,
    relation_endpoint_type_preferences,
)
from app.models.knowledge_taxonomy import (
    PARENT_KNOWLEDGE_UNIT_TYPES,
    PRIMARY_KNOWLEDGE_UNIT_TYPES,
    SECONDARY_KNOWLEDGE_UNIT_TYPES,
    STANDARD_KNOWLEDGE_UNIT_TYPES,
    STANDARD_RELATION_TYPES,
    normalize_knowledge_unit_type,
    normalize_relation_type,
    validate_relation_direction,
)
from app.workflows.digest.kg_doc_sync.prompts.section_graph import SYSTEM_PROMPT_KNOWLEDGE_EXTRACT


def test_learning_graph_ontology_matches_enum_values():
    assert STANDARD_KNOWLEDGE_UNIT_TYPES == {item.value for item in KnowledgeUnitType}
    assert STANDARD_RELATION_TYPES == {item.value for item in KnowledgeRelationType}
    assert PRIMARY_KNOWLEDGE_UNIT_TYPES | SECONDARY_KNOWLEDGE_UNIT_TYPES == STANDARD_KNOWLEDGE_UNIT_TYPES
    assert PRIMARY_KNOWLEDGE_UNIT_TYPES.isdisjoint(SECONDARY_KNOWLEDGE_UNIT_TYPES)
    assert PARENT_KNOWLEDGE_UNIT_TYPES == PRIMARY_KNOWLEDGE_UNIT_TYPES
    assert set(LEARNING_GRAPH_ONTOLOGY.unit_type_values) == STANDARD_KNOWLEDGE_UNIT_TYPES
    assert set(LEARNING_GRAPH_ONTOLOGY.relation_type_values) == STANDARD_RELATION_TYPES
    assert set(LEARNING_GRAPH_ONTOLOGY.primary_unit_type_values) == PRIMARY_KNOWLEDGE_UNIT_TYPES
    assert set(LEARNING_GRAPH_ONTOLOGY.secondary_unit_type_values) == SECONDARY_KNOWLEDGE_UNIT_TYPES
    assert set(LEARNING_GRAPH_ONTOLOGY.parent_unit_type_values) == PARENT_KNOWLEDGE_UNIT_TYPES


def test_section_graph_prompt_uses_canonical_ontology_bullets():
    unit_bullets = format_ontology_unit_type_bullets()
    relation_bullets = format_ontology_relation_type_bullets()
    direction_bullets = format_ontology_relation_direction_bullets()

    assert unit_bullets in SYSTEM_PROMPT_KNOWLEDGE_EXTRACT
    assert relation_bullets in SYSTEM_PROMPT_KNOWLEDGE_EXTRACT
    assert direction_bullets in SYSTEM_PROMPT_KNOWLEDGE_EXTRACT
    for spec in LEARNING_GRAPH_ONTOLOGY.unit_types:
        assert f"`{spec.value}`" in SYSTEM_PROMPT_KNOWLEDGE_EXTRACT
    for spec in LEARNING_GRAPH_ONTOLOGY.relation_types:
        assert f"`{spec.value}`" in SYSTEM_PROMPT_KNOWLEDGE_EXTRACT


def test_relation_direction_rules_match_kg_doc_sync_ontology():
    assert validate_relation_direction(
        edge_type="training",
        source_type="core_knowledge",
        target_type="practice_assessment",
    )
    assert validate_relation_direction(
        edge_type="explanation",
        source_type="core_knowledge",
        target_type="explanation_support",
    )
    assert validate_relation_direction(
        edge_type="application",
        source_type="method_demo",
        target_type="application_extension",
    )
    assert not validate_relation_direction(
        edge_type="training",
        source_type="practice_assessment",
        target_type="core_knowledge",
    )
    assert not validate_relation_direction(
        edge_type="explanation",
        source_type="explanation_support",
        target_type="core_knowledge",
    )
    assert not validate_relation_direction(
        edge_type="prerequisite",
        source_type="practice_assessment",
        target_type="core_knowledge",
    )
    for spec in LEARNING_GRAPH_ONTOLOGY.relation_types:
        assert spec.allows(source_type="core_knowledge", target_type="method_demo") == validate_relation_direction(
            edge_type=spec.value,
            source_type="core_knowledge",
            target_type="method_demo",
        )
        preferred_sources = relation_endpoint_type_preferences(spec.value, "source")
        preferred_targets = relation_endpoint_type_preferences(spec.value, "target")
        if preferred_sources and preferred_targets:
            assert validate_relation_direction(
                edge_type=spec.value,
                source_type=preferred_sources[0],
                target_type=preferred_targets[0],
            )


def test_ontology_supplies_extraction_relation_preferences():
    assert relation_endpoint_type_preferences("training", "target") == ("practice_assessment",)
    assert "core_knowledge" in relation_endpoint_type_preferences("reasoning", "target")
    assert default_relation_for_unit_type("method_demo") == "application"
    assert default_relation_for_unit_type("practice_assessment") == "training"
    assert default_relation_for_unit_type("explanation_support") == "explanation"
    assert default_relation_for_unit_type("principle_reasoning") == "reasoning"
    assert default_relation_for_unit_type("core_knowledge") == "contains"


def test_legacy_knowledge_graph_types_are_normalized_for_compatibility():
    assert normalize_knowledge_unit_type("concept") == "core_knowledge"
    assert normalize_knowledge_unit_type("definition") == "core_knowledge"
    assert normalize_knowledge_unit_type("formula") == "core_knowledge"
    assert normalize_knowledge_unit_type("method") == "method_demo"
    assert normalize_knowledge_unit_type("example") == "method_demo"
    assert normalize_knowledge_unit_type("exercise") == "practice_assessment"
    assert normalize_knowledge_unit_type("proof_step") == "principle_reasoning"
    assert normalize_knowledge_unit_type("remark") == "explanation_support"
    assert normalize_relation_type("derivation") == "reasoning"
    assert normalize_relation_type("example_of") == "training"
    assert normalize_relation_type("support") == "explanation"
    assert normalize_relation_type("related") == "application"
    assert normalize_relation_type("remark") == "explanation"
    assert normalize_relation_type("practice_assessment") == "training"
