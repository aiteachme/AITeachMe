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
