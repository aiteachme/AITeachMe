from app.api.exams import _question_template_refs_with_metadata
from app.models.knowledge_unit import KnowledgeUnit


def test_question_template_refs_include_display_metadata() -> None:
    knowledge_unit = KnowledgeUnit(
        id=136,
        course_id="course-detail",
        knowledge_unit_type="skill",
        canonical_name="折线图中的分段函数建模",
        normalized_name="折线图中的分段函数建模",
    )

    refs = _question_template_refs_with_metadata(
        [{"knowledge_unit_id": 136, "coverage_weight": 0.45}],
        knowledge_unit_by_id={136: knowledge_unit},
    )

    assert refs == [
        {
            "knowledge_unit_id": 136,
            "coverage_weight": 0.45,
            "knowledge_unit_name": "折线图中的分段函数建模",
            "knowledge_unit_type": "skill",
            "knowledge_unit_type_label": "解题技能",
        }
    ]


def test_question_template_refs_keep_missing_unit_links_readable() -> None:
    refs = _question_template_refs_with_metadata(
        [{"knowledge_unit_id": 999, "coverage_weight": 1.0}],
        knowledge_unit_by_id={},
    )

    assert refs == [{"knowledge_unit_id": 999, "coverage_weight": 1.0}]
