"""Repository package exports with lazy loading."""

from __future__ import annotations

from importlib import import_module

__all__ = ["curriculum_repo", "exams_repo", "kg_repo", "knowledge_repo", "profile_repo"]

_ATTR_TO_MODULE = {
    "curriculum_repo": "app.repositories.knowledge.curriculum_repo",
    "exams_repo": "app.repositories.exams_repo",
    "kg_repo": "app.repositories.knowledge.kg_repo",
    "knowledge_repo": "app.repositories.knowledge.knowledge_repo",
    "profile_repo": "app.repositories.profile_repo",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    globals()[name] = module
    return module
