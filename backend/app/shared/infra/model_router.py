"""Compatibility shim for legacy model routing imports.

Canonical LLM routing logic now lives in `app.shared.infra.llm_support.routing`.
"""

from app.shared.infra.llm_support.routing import TaskProfile, TaskType, get_task_profile

__all__ = ["TaskProfile", "TaskType", "get_task_profile"]
