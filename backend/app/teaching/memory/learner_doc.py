"""Compatibility facade for the canonical learner-doc helpers."""

from app.shared.infra.memory.learner_doc import (
    append_to_learner_section,
    get_learner_doc_path,
    load_doc_to_context,
    read_learner_doc,
    read_learner_section,
    sync_profile_to_doc,
    update_learner_section,
    write_learner_doc,
)

__all__ = [
    "append_to_learner_section",
    "get_learner_doc_path",
    "load_doc_to_context",
    "read_learner_doc",
    "read_learner_section",
    "sync_profile_to_doc",
    "update_learner_section",
    "write_learner_doc",
]
