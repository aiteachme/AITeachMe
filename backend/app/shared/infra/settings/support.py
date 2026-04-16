"""Helpers for loading project runtime configuration from `settings.yaml`."""

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
    "planner_fast": ["local_rag", "searxng", "bocha", "duckduckgo"],
    "planner_grounding": ["local_rag", "searxng", "bocha", "duckduckgo"],
    "docgen_balanced": ["local_rag", "searxng", "tavily", "bocha", "duckduckgo"],
    "docgen_sprint": ["local_rag", "searxng", "tavily", "bocha", "duckduckgo"],
    "docgen_academic": ["local_rag", "searxng", "tavily", "arxiv", "semantic_scholar", "duckduckgo"],
    "docgen_systematic": ["local_rag", "searxng", "tavily", "arxiv", "semantic_scholar", "duckduckgo"],
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
    """Parse the small repo-root `settings.yaml` mapping."""

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
    return raw


__all__ = [
    "DEFAULT_EMBEDDING_DIM",
    "DEFAULT_RETRIEVER_FALLBACK",
    "EMBEDDING_DIM_BY_MODEL",
    "RETRIEVER_PROFILES",
    "load_project_settings_values",
    "normalize_retriever_name",
    "split_csv_names",
]
