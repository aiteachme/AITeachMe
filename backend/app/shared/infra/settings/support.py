"""Helpers for loading project runtime configuration from `settings_default.yaml`."""

from __future__ import annotations

from functools import lru_cache
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
DEFAULT_RETRIEVERS: list[str] = [
    "local_rag",
    "searxng",
    "tavily",
    "bocha",
    "brave",
    "exa",
    "bing",
    "arxiv",
    "semantic_scholar",
    "duckduckgo",
]
DEFAULT_RETRIEVER_PROFILES: dict[str, list[str]] = {
    "planner_fast": list(DEFAULT_RETRIEVERS),
    "planner_grounding": list(DEFAULT_RETRIEVERS),
    "docgen_balanced": list(DEFAULT_RETRIEVERS),
    "docgen_sprint": list(DEFAULT_RETRIEVERS),
    "docgen_academic": list(DEFAULT_RETRIEVERS),
    "docgen_systematic": list(DEFAULT_RETRIEVERS),
}
RETRIEVER_PROFILES = DEFAULT_RETRIEVER_PROFILES


def split_csv_names(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in str(value).split(",") if item and item.strip()]


def normalize_retriever_name(name: str) -> str:
    normalized = (name or "").strip().lower()
    return RETRIEVER_ALIASES.get(normalized, normalized)


def normalize_profile_name(name: str) -> str:
    return (name or "").strip().lower()


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
    if text == "{}":
        return {}
    if text == "[]":
        return []
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
    """Parse the small repo-root `settings_default.yaml` mapping."""

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


def load_project_settings_values(path: Path | None = None) -> dict[str, Any]:
    current_path = path
    if current_path is None:
        from app.shared.infra.env_support import resolve_project_settings_path

        current_path = resolve_project_settings_path()
    if not current_path.exists():
        return {}
    try:
        raw = parse_yaml_mapping(current_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _normalize_profile_entries(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_names = split_csv_names(value)
    elif isinstance(value, list):
        raw_names = [str(item).strip() for item in value if str(item).strip()]
    else:
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_names:
        name = normalize_retriever_name(str(item))
        if not name or name in seen:
            continue
        seen.add(name)
        normalized.append(name)
    return normalized


def _iter_retriever_profile_override_blocks(raw: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for key in ("retriever_profiles",):
        candidate = raw.get(key)
        if isinstance(candidate, dict):
            blocks.append(candidate)
    for scope_key in ("search", "web_search"):
        scope_value = raw.get(scope_key)
        if not isinstance(scope_value, dict):
            continue
        candidate = scope_value.get("retriever_profiles")
        if isinstance(candidate, dict):
            blocks.append(candidate)
    return blocks


@lru_cache(maxsize=1)
def get_retriever_profiles(path: Path | None = None) -> dict[str, list[str]]:
    profiles = {
        normalize_profile_name(name): list(values)
        for name, values in DEFAULT_RETRIEVER_PROFILES.items()
    }
    raw = load_project_settings_values(path)
    for block in _iter_retriever_profile_override_blocks(raw):
        for name, value in block.items():
            profile_name = normalize_profile_name(str(name))
            if not profile_name:
                continue
            entries = _normalize_profile_entries(value)
            if entries:
                profiles[profile_name] = entries
    return profiles


__all__ = [
    "DEFAULT_EMBEDDING_DIM",
    "DEFAULT_RETRIEVER_FALLBACK",
    "DEFAULT_RETRIEVER_PROFILES",
    "DEFAULT_RETRIEVERS",
    "EMBEDDING_DIM_BY_MODEL",
    "RETRIEVER_PROFILES",
    "get_retriever_profiles",
    "load_project_settings_values",
    "normalize_profile_name",
    "normalize_retriever_name",
    "split_csv_names",
]
