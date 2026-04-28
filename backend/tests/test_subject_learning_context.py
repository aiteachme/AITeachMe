from __future__ import annotations

from app.workflows.support.subjects.learning_context import build_subject_learning_context_payload


def test_subject_learning_context_payload_uses_explicit_subject_fields() -> None:
    _intent, _intro, payload, _llm_context = build_subject_learning_context_payload(
        subject_id="subj_context",
        subject_name="计算机基础",
        document_context={"digest_mode": "sprint"},
        chapter_metadatas=[],
        chapter_assignments=[],
        knowledge_docs=[],
        docgen_artifacts={},
    )

    assert payload["subject_id"] == "subj_context"
    assert payload["subject_name"] == "计算机基础"
    assert "subject" not in payload
