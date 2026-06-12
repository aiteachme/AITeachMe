from app.models.enums import KnowledgeRelationType, KnowledgeUnitType
from app.workflows.digest.kg_doc_sync.lib.ontology import (
    LEARNING_GRAPH_ONTOLOGY,
    default_relation_for_unit_type,
    format_ontology_relation_direction_bullets,
    format_ontology_relation_type_bullets,
    format_ontology_unit_type_bullets,
    relation_endpoint_type_preferences,
)
from app.workflows.digest.kg_doc_sync.prompts.section_graph import SYSTEM_PROMPT_KNOWLEDGE_EXTRACT
from app.models.knowledge_taxonomy import (
    PARENT_KNOWLEDGE_UNIT_TYPES,
    PRIMARY_KNOWLEDGE_UNIT_TYPES,
    SECONDARY_KNOWLEDGE_UNIT_TYPES,
    STANDARD_KNOWLEDGE_UNIT_TYPES,
    STANDARD_RELATION_TYPES,
    knowledge_unit_type_label,
    normalize_knowledge_unit_type,
    normalize_relation_type,
    relation_type_label,
    validate_relation_direction,
)


def test_learning_graph_ontology_matches_enum_values():
    assert STANDARD_KNOWLEDGE_UNIT_TYPES == {item.value for item in KnowledgeUnitType}
    assert STANDARD_RELATION_TYPES == {item.value for item in KnowledgeRelationType}
    assert PRIMARY_KNOWLEDGE_UNIT_TYPES | SECONDARY_KNOWLEDGE_UNIT_TYPES == STANDARD_KNOWLEDGE_UNIT_TYPES
    assert PRIMARY_KNOWLEDGE_UNIT_TYPES.isdisjoint(SECONDARY_KNOWLEDGE_UNIT_TYPES)
    assert PARENT_KNOWLEDGE_UNIT_TYPES <= STANDARD_KNOWLEDGE_UNIT_TYPES
    assert set(LEARNING_GRAPH_ONTOLOGY.unit_type_values) == STANDARD_KNOWLEDGE_UNIT_TYPES
    assert set(LEARNING_GRAPH_ONTOLOGY.relation_type_values) == STANDARD_RELATION_TYPES
    assert set(LEARNING_GRAPH_ONTOLOGY.primary_unit_type_values) == PRIMARY_KNOWLEDGE_UNIT_TYPES
    assert set(LEARNING_GRAPH_ONTOLOGY.secondary_unit_type_values) == SECONDARY_KNOWLEDGE_UNIT_TYPES
    assert set(LEARNING_GRAPH_ONTOLOGY.parent_unit_type_values) == PARENT_KNOWLEDGE_UNIT_TYPES


def test_knowledge_graph_type_labels_are_chinese_and_stable():
    assert knowledge_unit_type_label("concept") == "概念术语"
    assert knowledge_unit_type_label("formula") == "公式模型"
    assert relation_type_label("prerequisite_for") == "前置"
    assert relation_type_label("derivation") == "推导"


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
        edge_type="assesses",
        source_type="skill",
        target_type="concept",
    )
    assert validate_relation_direction(
        edge_type="explains",
        source_type="resource",
        target_type="concept",
    )
    assert validate_relation_direction(
        edge_type="applies_to",
        source_type="concept",
        target_type="application_case",
    )
    assert not validate_relation_direction(
        edge_type="assesses",
        source_type="concept",
        target_type="skill",
    )
    assert not validate_relation_direction(
        edge_type="explains",
        source_type="concept",
        target_type="resource",
    )
    assert not validate_relation_direction(
        edge_type="prerequisite_for",
        source_type="resource",
        target_type="concept",
    )
    for spec in LEARNING_GRAPH_ONTOLOGY.relation_types:
        assert spec.allows(source_type="concept", target_type="procedure") == validate_relation_direction(
            edge_type=spec.value,
            source_type="concept",
            target_type="procedure",
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
    assert relation_endpoint_type_preferences("assesses", "target")[0] == "concept"
    assert "procedure" in relation_endpoint_type_preferences("derives_to", "target")
    assert default_relation_for_unit_type("procedure") == "part_of"
    assert default_relation_for_unit_type("skill") == "assesses"
    assert default_relation_for_unit_type("resource") == "explains"
    assert default_relation_for_unit_type("principle") == "derives_to"
    assert default_relation_for_unit_type("concept") == "part_of"


def test_legacy_knowledge_graph_types_are_normalized_for_compatibility():
    assert normalize_knowledge_unit_type("concept") == "concept"
    assert normalize_knowledge_unit_type("definition") == "concept"
    assert normalize_knowledge_unit_type("formula") == "formula_model"
    assert normalize_knowledge_unit_type("method") == "procedure"
    assert normalize_knowledge_unit_type("example") == "application_case"
    assert normalize_knowledge_unit_type("exercise") == "skill"
    assert normalize_knowledge_unit_type("proof_step") == "principle"
    assert normalize_knowledge_unit_type("remark") == "resource"
    assert normalize_relation_type("derivation") == "derives_to"
    assert normalize_relation_type("example_of") == "applies_to"
    assert normalize_relation_type("support") == "explains"
    assert normalize_relation_type("related") == "applies_to"
    assert normalize_relation_type("remark") == "explains"
    assert normalize_relation_type("practice_assessment") == "assesses"
