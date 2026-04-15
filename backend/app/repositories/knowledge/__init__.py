"""Knowledge repository package exports with lazy loading."""

from __future__ import annotations

from importlib import import_module

__all__ = ["docgen_repo", "kg_repo", "knowledge_repo"]

_ATTR_TO_MODULE = {
    "docgen_repo": "app.repositories.knowledge.docgen_repo",
    "kg_repo": "app.repositories.knowledge.kg_repo",
    "knowledge_repo": "app.repositories.knowledge.knowledge_repo",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    globals()[name] = module
    return module
