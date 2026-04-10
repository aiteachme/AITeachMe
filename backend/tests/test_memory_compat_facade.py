from __future__ import annotations

from app.shared.infra import memory as infra_memory
from app.teaching import memory as teaching_memory


def test_teaching_memory_reexports_canonical_memory_api() -> None:
    assert teaching_memory.remember is infra_memory.remember
    assert teaching_memory.recall is infra_memory.recall
    assert teaching_memory.forget is infra_memory.forget
    assert teaching_memory.get_user_profile is infra_memory.get_user_profile
    assert teaching_memory.log_learning_event is infra_memory.log_learning_event


def test_teaching_memory_reexports_canonical_learner_doc_helpers() -> None:
    assert teaching_memory.get_learner_doc_path is infra_memory.get_learner_doc_path
    assert teaching_memory.read_learner_doc is infra_memory.read_learner_doc
    assert teaching_memory.update_learner_section is infra_memory.update_learner_section
    assert teaching_memory.sync_profile_to_doc is infra_memory.sync_profile_to_doc
