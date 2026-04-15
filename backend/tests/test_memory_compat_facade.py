from __future__ import annotations

from app.shared.infra import memory as infra_memory


def test_infra_memory_exports_canonical_memory_api() -> None:
    assert callable(infra_memory.remember)
    assert callable(infra_memory.recall)
    assert callable(infra_memory.forget)
    assert callable(infra_memory.get_user_profile)
    assert callable(infra_memory.log_learning_event)


def test_infra_memory_exports_canonical_learner_doc_helpers() -> None:
    assert callable(infra_memory.get_learner_doc_path)
    assert callable(infra_memory.read_learner_doc)
    assert callable(infra_memory.update_learner_section)
    assert callable(infra_memory.sync_profile_to_doc)
