"""Code-owned runtime defaults for project settings."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from .support import get_llm_provider_model_defaults, resolve_runtime_llm_provider

SPRINT_MODE_DEFAULTS: dict[str, Any] = {
    "min_chapters": 4,
    "max_chapters": 7,
    "target_length": "3000-5000字",
}

SYSTEMATIC_MODE_DEFAULTS: dict[str, Any] = {
    "min_chapters": 5,
    "max_chapters": 12,
    "target_length": "10000-15000字",
}

DEFAULT_SETTINGS_VALUES: dict[str, Any] = {
    "models": {
        "embedding_dim": None,
    },
    "interact": {
        "history_turns": 10,
    },
    "planner": {
        "default_digest_mode": "sprint",
        "sprint": SPRINT_MODE_DEFAULTS,
        "systematic": SYSTEMATIC_MODE_DEFAULTS,
    },
    "docgen": {
        "allow_external_search": True,
        "generate_cover_image": False,
    },
    "ingest": {
        "max_upload_size_mb": 10,
        "max_files_per_upload": 10,
    },
    "rag": {
        "top_k": 5,
        "similarity_threshold": 0.3,
        "rerank_model": None,
        "rerank_top_k": 3,
    },
    "local_rag": {
        "priority": True,
        "min_results": 2,
    },
    "knowledge_graph": {
        "sync_after_docgen": False,
    },
    "observability": {
        "llm_observability_enabled": True,
        "llm_token_summary_enabled": True,
        "tracing_enabled": True,
    },
}



def get_default_settings_values() -> dict[str, Any]:
    """Return a deep-copied settings payload owned by code defaults."""

    values = deepcopy(DEFAULT_SETTINGS_VALUES)
    values["models"] = merge_settings_values(
        values["models"],
        get_llm_provider_model_defaults(resolve_runtime_llm_provider()),
    )
    return values


def merge_settings_values(
    base: Mapping[str, Any],
    override: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Recursively merge two settings-shaped mappings."""

    merged = deepcopy(dict(base))
    for key, value in dict(override or {}).items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), dict):
            merged[key] = merge_settings_values(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def merge_default_settings(override: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Merge project overrides on top of code-owned defaults."""

    return merge_settings_values(get_default_settings_values(), override)


__all__ = [
    "DEFAULT_SETTINGS_VALUES",
    "get_default_settings_values",
    "merge_default_settings",
    "merge_settings_values",
]
