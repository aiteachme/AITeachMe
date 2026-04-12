"""Internal helpers for the public `app.shared.infra.config` entrypoint."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

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
}
RETRIEVER_PROFILES: dict[str, list[str]] = {
    "planner_fast": ["local_rag", "bocha", "duckduckgo"],
    "planner_grounding": ["local_rag", "bocha", "duckduckgo"],
    "docgen_balanced": ["local_rag", "tavily", "bocha"],
    "docgen_sprint": ["local_rag", "tavily", "bocha"],
    "docgen_academic": ["local_rag", "tavily", "arxiv", "semantic_scholar"],
    "docgen_systematic": ["local_rag", "tavily", "arxiv", "semantic_scholar"],
}

PROJECT_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_PROJECT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"
DOTENV_CANDIDATES = (
    PROJECT_ROOT / ".env",
    PROJECT_ROOT / "backend" / ".env",
)
CONFIG_YAML_FIELD_MAP: dict[str, str] = {
    "models_primary": "llm_model",
    "models_light": "llm_model_light",
    "models_extract": "llm_model_extract",
    "models_ocr": "ocr_model",
    "models_embedding": "embedding_model",
    "models_image_generation": "image_generation_model",
    "models_mermaid_generation": "mermaid_generation_model",
    "files_max_upload_size_mb": "max_upload_size_mb",
    "runtime_llm_concurrency_limit": "llm_concurrency_limit",
    "runtime_default_token_budget": "default_token_budget",
    "observability_llm_observability_enabled": "llm_observability_enabled",
    "observability_tracing_enabled": "tracing_enabled",
    "features_enable_image_generation": "enable_image_generation",
    "features_enable_mermaid_generation": "enable_mermaid_generation",
    "features_image_generation_model": "image_generation_model",
    "features_mermaid_generation_model": "mermaid_generation_model",
    "observability_llm_observability_max_records": "llm_observability_max_records",
    "safety_guardrails_enabled": "guardrails_enabled",
    "cache_enabled": "llm_cache_enabled",
    "cache_ttl_s": "llm_cache_ttl_s",
    "cache_max_entries": "llm_cache_max_entries",
    "knowledge_graph_extract_max_parallelism": "kg_extract_max_parallelism",
    "langsmith_max_text_chars": "langsmith_max_text_chars",
}
CONFIG_YAML_DIRECT_FIELDS = frozenset(
    {
        "ingest_parse_concurrency",
        "ingest_parser_timeout_s",
        "rag_top_k",
        "rag_similarity_threshold",
        "chat_history_turns",
        "langsmith_tracing",
        "langsmith_project",
        "langsmith_capture_inputs",
        "langsmith_capture_outputs",
        "embedding_batch_size",
        "embedding_batch_delay_s",
        "digest_timing_top_k",
        "digest_token_summary_enabled",
        "digest_chapter_priors_timeout_ms",
        "docgen_max_parallel_chapters",
        "docgen_io_parallelism",
        "docgen_max_research_queries",
        "web_search_retriever",
        "web_search_retrievers",
        "web_search_retriever_profile",
        "local_rag_priority",
        "local_rag_min_results",
        "search_max_results_per_query",
        "search_scrape_timeout_s",
        "planner_default_tone",
        "planner_default_digest_mode",
        "planner_allow_external_search",
        "planner_sprint_min_chapters",
        "planner_sprint_max_chapters",
        "planner_sprint_target_length",
        "planner_systematic_min_chapters",
        "planner_systematic_max_chapters",
        "planner_systematic_target_length",
    }
)
CONFIG_YAML_ONLY_FIELDS = frozenset(CONFIG_YAML_FIELD_MAP.values()) | CONFIG_YAML_DIRECT_FIELDS


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


def read_dotenv_value(name: str) -> str | None:
    for path in DOTENV_CANDIDATES:
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, raw_value = line.partition("=")
            if key.strip() != name:
                continue
            value = raw_value.strip().strip('"').strip("'")
            return value or None
    return None


def resolve_project_config_path() -> Path:
    configured = (
        os.getenv("PROJECT_CONFIG_PATH")
        or read_dotenv_value("PROJECT_CONFIG_PATH")
        or str(DEFAULT_PROJECT_CONFIG_PATH)
    ).strip()
    path = Path(configured)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def load_project_config_values() -> dict[str, Any]:
    path = resolve_project_config_path()
    if not path.exists():
        return {}
    try:
        raw = parse_yaml_mapping(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return flatten_project_config(raw)


class ProjectYamlSettingsSource(PydanticBaseSettingsSource):
    """Settings source backed by repo-root `config.yaml`."""

    def __init__(self, settings_cls: type[BaseSettings]):
        super().__init__(settings_cls)
        self._data = load_project_config_values()

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        del field
        return self._data.get(field_name), field_name, False

    def __call__(self) -> dict[str, Any]:
        return dict(self._data)


class FilteredSettingsSource(PydanticBaseSettingsSource):
    """Wrap a settings source and drop fields owned by `config.yaml`."""

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        source: PydanticBaseSettingsSource,
        *,
        blocked_fields: frozenset[str],
    ):
        super().__init__(settings_cls)
        self._source = source
        self._blocked_fields = blocked_fields

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        if field_name in self._blocked_fields:
            return None, field_name, False
        return self._source.get_field_value(field, field_name)

    def __call__(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in self._source().items()
            if key not in self._blocked_fields
        }


def build_settings_sources(
    settings_cls: type[BaseSettings],
    init_settings: PydanticBaseSettingsSource,
    env_settings: PydanticBaseSettingsSource,
    dotenv_settings: PydanticBaseSettingsSource,
    file_secret_settings: PydanticBaseSettingsSource,
) -> tuple[PydanticBaseSettingsSource, ...]:
    return (
        init_settings,
        FilteredSettingsSource(
            settings_cls,
            env_settings,
            blocked_fields=CONFIG_YAML_ONLY_FIELDS,
        ),
        FilteredSettingsSource(
            settings_cls,
            dotenv_settings,
            blocked_fields=CONFIG_YAML_ONLY_FIELDS,
        ),
        ProjectYamlSettingsSource(settings_cls),
        file_secret_settings,
    )


__all__ = [
    "DEFAULT_EMBEDDING_DIM",
    "DEFAULT_RETRIEVER_FALLBACK",
    "EMBEDDING_DIM_BY_MODEL",
    "RETRIEVER_PROFILES",
    "build_settings_sources",
    "normalize_retriever_name",
    "resolve_project_config_path",
    "split_csv_names",
]
