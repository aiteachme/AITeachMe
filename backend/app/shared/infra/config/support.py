"""Helpers for loading project runtime configuration from `config.yaml`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

EMBEDDING_DIM_BY_MODEL: dict[str, int] = {
    "text-embedding-v4": 1024,
    "text-embedding-v3": 1536,
    "text-embedding-v2": 1536,
    "text-embedding-ada-002": 1536,
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "BAAI/bge-large-zh-v1.5": 1024,
    "BAAI/bge-m3": 1024,
    "qwen3-embedding-8b": 4096,
    "qwen3-embedding-0.6b": 1024,
}
DEFAULT_EMBEDDING_DIM = 1536
DEFAULT_RETRIEVER_FALLBACK = "duckduckgo"
RETRIEVER_ALIASES: dict[str, str] = {
    "ddg": "duckduckgo",
    "rag": "local_rag",
    "searx": "searxng",
    "wiki": "wikipedia",
}
RETRIEVER_PROFILES: dict[str, list[str]] = {
    "planner_fast": ["local_rag", "wikipedia", "searxng", "bocha", "duckduckgo"],
    "planner_grounding": ["local_rag", "wikipedia", "searxng", "bocha", "duckduckgo"],
    "docgen_balanced": ["local_rag", "wikipedia", "searxng", "tavily", "bocha", "duckduckgo"],
    "docgen_sprint": ["local_rag", "wikipedia", "searxng", "tavily", "bocha", "duckduckgo"],
    "docgen_academic": ["local_rag", "wikipedia", "searxng", "tavily", "arxiv", "semantic_scholar", "duckduckgo"],
    "docgen_systematic": ["local_rag", "wikipedia", "searxng", "tavily", "arxiv", "semantic_scholar", "duckduckgo"],
}

CONFIG_YAML_FIELD_MAP: dict[str, str] = {
    "models_reason": "llm_model_reason",
    "models_primary": "llm_model",
    "models_light": "llm_model_light",
    "models_extract": "llm_model_extract",
    "models_ocr": "ocr_model",
    "models_embedding": "embedding_model",
    "models_image_generation": "image_generation_model",
    "models_mermaid_generation": "mermaid_generation_model",
    "files_max_upload_size_mb": "max_upload_size_mb",
    "chat_history_turns": "chat_history_turns",
    "runtime_llm_concurrency_limit": "llm_concurrency_limit",
    "runtime_default_token_budget": "default_token_budget",
    "observability_llm_observability_enabled": "llm_observability_enabled",
    "observability_tracing_enabled": "tracing_enabled",
    "observability_llm_observability_max_records": "llm_observability_max_records",
    "features_enable_image_generation": "enable_image_generation",
    "features_enable_mermaid_generation": "enable_mermaid_generation",
    "features_image_generation_model": "image_generation_model",
    "features_mermaid_generation_model": "mermaid_generation_model",
    "safety_guardrails_enabled": "guardrails_enabled",
    "cache_enabled": "llm_cache_enabled",
    "cache_ttl_s": "llm_cache_ttl_s",
    "cache_max_entries": "llm_cache_max_entries",
    "knowledge_graph_extract_max_parallelism": "kg_extract_max_parallelism",
}


def split_csv_names(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in str(value).split(",") if item and item.strip()]


def normalize_retriever_name(name: str) -> str:
    normalized = (name or "").strip().lower()
    return RETRIEVER_ALIASES.get(normalized, normalized)


def parse_yaml_scalar(value: str) -> Any:
    text = value.strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return text[1:-1]
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def parse_yaml_mapping(text: str) -> dict[str, Any]:
    """Parse the small repo-root `config.yaml` mapping."""

    try:
        import yaml  # type: ignore

        parsed = yaml.safe_load(text) or {}
        return parsed if isinstance(parsed, dict) else {}
    except ImportError:
        pass

    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()

        current = stack[-1][1]
        key, sep, raw_value = stripped.partition(":")
        if not sep:
            continue

        normalized_key = key.strip().replace("-", "_")
        value = raw_value.strip()
        if not value:
            child: dict[str, Any] = {}
            current[normalized_key] = child
            stack.append((indent, child))
            continue
        current[normalized_key] = parse_yaml_scalar(value)

    return root


def flatten_project_config(raw: dict[str, Any], *, prefix: str = "") -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, value in raw.items():
        normalized_key = str(key).strip().replace("-", "_")
        full_key = f"{prefix}_{normalized_key}" if prefix else normalized_key
        if isinstance(value, dict):
            flattened.update(flatten_project_config(value, prefix=full_key))
            continue
        flattened[CONFIG_YAML_FIELD_MAP.get(full_key, full_key)] = value
    return flattened


def load_project_config_values(path: Path | None = None) -> dict[str, Any]:
    current_path = path
    if current_path is None:
        from app.shared.infra.env_support import resolve_project_config_path

        current_path = resolve_project_config_path()
    if not current_path.exists():
        return {}
    try:
        raw = parse_yaml_mapping(current_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return flatten_project_config(raw)


__all__ = [
    "DEFAULT_EMBEDDING_DIM",
    "DEFAULT_RETRIEVER_FALLBACK",
    "EMBEDDING_DIM_BY_MODEL",
    "RETRIEVER_PROFILES",
    "load_project_config_values",
    "normalize_retriever_name",
    "split_csv_names",
]
