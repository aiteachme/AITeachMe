"""多层记忆系统 — 对外极简 API。"""
from app.teaching.memory.api import (
    forget,
    get_learning_log,
    get_user_profile,
    recall,
    remember,
)
from app.teaching.memory.learner_doc import (
    append_to_learner_section,
    get_learner_doc_path,
    load_doc_to_context,
    read_learner_doc,
    read_learner_section,
    sync_profile_to_doc,
    update_learner_section,
    write_learner_doc,
)
from app.teaching.memory.profile import UserProfile
from app.teaching.memory.types import LearningLogEntry, MemoryEntry, MemoryTag

__all__ = [
    "forget",
    "get_learning_log",
    "get_user_profile",
    "recall",
    "remember",
    "append_to_learner_section",
    "get_learner_doc_path",
    "load_doc_to_context",
    "read_learner_doc",
    "read_learner_section",
    "sync_profile_to_doc",
    "update_learner_section",
    "write_learner_doc",
    "LearningLogEntry",
    "MemoryEntry",
    "MemoryTag",
    "UserProfile",
]
