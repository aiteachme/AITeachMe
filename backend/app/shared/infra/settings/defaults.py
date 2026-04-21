"""Code-owned runtime defaults for project settings."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

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
        "reason": "qwen-max",
        "primary": "qwen-flash",
        "light": "qwen-flash",
        "extract": None,
        "ocr": None,
        "embedding": "text-embedding-v3",
        "image_generation": None,
        "overrides": {},
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
        "max_parallel_chapters": 20,
        "io_parallelism": 20,
        "max_research_queries": 3,
        "retrieval_timeout_s": 18.0,
        "read_timeout_s": 12.0,
    },
    "ingest": {
        "default_parser_provider": "auto",
        "max_upload_size_mb": 10,
        "max_files_per_upload": 10,
        "parse_concurrency": 5,
        "parser_timeout_s": 90,
        "mineru_model_version": "vlm",
        "mineru_enable_formula": True,
        "mineru_enable_table": True,
        "mineru_is_ocr": False,
    },
    "rag": {
        "top_k": 5,
        "similarity_threshold": 0.3,
        "rerank_model": None,
        "rerank_top_k": 3,
    },
    "search": {
        "retrievers": "",
        "retriever_profile": "",
        "max_results_per_query": 5,
        "scrape_timeout_s": 20,
        "provider_timeout_s": 6.0,
        "total_timeout_s": 12.0,
        "read_timeout_s": 10.0,
        "parallel_retrievers": True,
        "max_parallel_retrievers": 4,
        "fusion_k": 60,
        "runtime_cache_enabled": True,
        "runtime_cache_ttl_s": 900,
        "runtime_cache_max_entries": 256,
        "retriever_profiles": {},
    },
    "local_rag": {
        "priority": True,
        "min_results": 2,
    },
    "runtime": {
        "llm_concurrency_limit": 20,
        "default_token_budget": 4000,
    },
    "embedding": {
        "batch_size": 10,
        "batch_delay_s": 0.1,
    },
    "knowledge_graph": {
        "extract_max_parallelism": 20,
        "sync_after_docgen": False,
    },
    "observability": {
        "llm_observability_enabled": True,
        "llm_token_summary_enabled": True,
        "timing_top_k": 5,
        "tracing_enabled": True,
        "langsmith_capture_inputs": None,
        "langsmith_capture_outputs": None,
        "langsmith_max_text_chars": 100000,
        "llm_observability_max_records": 1000,
    },
}



def get_default_settings_values() -> dict[str, Any]:
    """Return a deep-copied settings payload owned by code defaults."""

    return deepcopy(DEFAULT_SETTINGS_VALUES)


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

    return merge_settings_values(DEFAULT_SETTINGS_VALUES, override)


__all__ = [
    "DEFAULT_SETTINGS_VALUES",
    "get_default_settings_values",
    "merge_default_settings",
    "merge_settings_values",
]
