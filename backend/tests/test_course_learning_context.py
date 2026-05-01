from __future__ import annotations

from app.workflows.support.courses.learning_context import build_course_learning_context_payload


def test_course_learning_context_payload_uses_explicit_course_fields() -> None:
    _intent, _intro, payload, _llm_context = build_course_learning_context_payload(
        course_id="course_context",
        course_name="计算机基础",
        document_context={"digest_mode": "sprint"},
        chapter_metadatas=[],
        chapter_assignments=[],
        knowledge_docs=[],
        docgen_artifacts={},
    )

    assert payload["course_id"] == "course_context"
    assert payload["course_name"] == "计算机基础"
    assert "course" not in payload


def test_course_learning_context_payload_persists_docgen_signals() -> None:
    _intent, _intro, payload, llm_context = build_course_learning_context_payload(
        course_id="course_context",
        course_name="泛化学习材料",
        document_context={
            "digest_mode": "systematic",
            "retrieval_policy": {
                "local_first": True,
                "source_priority": ["local_materials", "general_learning_sources"],
            },
        },
        chapter_metadatas=[
            {
                "chapter_index": 1,
                "title": "第一章",
                "summary": "建立核心概念。",
                "source_file_ids": ["file_1"],
            }
        ],
        chapter_assignments=[],
        knowledge_docs=[],
        docgen_artifacts={
            "intent_profile": {
                "learning_goal_text": "学会材料主线",
                "content_strategy_text": "先讲主线，再用例子迁移。",
                "example_practice_policy": "例子用于验证理解。",
                "source_usage_policy": "优先使用本地资料。",
                "example_ratio": 0.3,
                "practice_ratio": 0.2,
            },
            "chapter_generation_plan": {
                "chapters": [
                    {
                        "chapter_index": 1,
                        "concept_targets": ["核心概念"],
                        "example_targets": ["代表性例子"],
                        "source_slices": [
                            {
                                "chapter_index": 1,
                                "file_id": "file_1",
                                "section_ref": "file_1#s1",
                                "summary": "原文片段摘要",
                            }
                        ],
                    }
                ]
            },
            "document_backbone_snapshot": {
                "canonical_glossary": [
                    {"term": "核心概念", "definition": "材料中的关键概念", "target_chapters": [1]}
                ],
                "canonical_claim_pool": [
                    {"claim_text": "核心概念需要结合例子理解", "target_chapter": 1}
                ],
            },
            "review_actions": [{"action_type": "evidence_patch"}],
            "repair_trace": [{"status": "applied"}],
        },
    )

    assert payload["schema_version"] == 2
    assert payload["intent_profile_v2"]["learning_goal_text"] == "学会材料主线"
    assert payload["retrieval_policy"]["local_first"] is True
    assert payload["kg_candidate_hints"][0]["candidate_terms"] == ["核心概念"]
    assert payload["quality_summary"]["applied_patch_count"] == 1
    assert "生成意图" in llm_context
    assert "图谱候选线索" in llm_context
