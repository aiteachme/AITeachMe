"""Compatibility facade for the canonical memory API."""

from app.shared.infra.memory.api import (
    forget,
    get_learning_log,
    get_user_profile,
    log_learning_event,
    recall,
    remember,
)

__all__ = [
    "forget",
    "get_learning_log",
    "get_user_profile",
    "log_learning_event",
    "recall",
    "remember",
]
