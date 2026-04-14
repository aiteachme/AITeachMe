"""LangSmith value sanitization and redaction helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import json

from app.shared.infra.config import get_settings
from app.shared.infra.env_support import get_env_int

_SAFE_LANGSMITH_FIELDS = {
    "content_type",
    "finish_reason",
    "id",
    "model",
    "name",
    "reader_name",
    "retriever_name",
    "role",
    "source",
    "tool_call_id",
    "type",
    "url",
}


def get_langsmith_max_text_chars() -> int:
    return max(32, get_env_int("LANGSMITH_MAX_TEXT_CHARS", 2000))


def _serialize_langsmith_value(value: Any) -> Any:
    if hasattr(value, "model_dump") and callable(getattr(value, "model_dump", None)):
        value = value.model_dump(mode="json")
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _redacted_data_url(text: str) -> str:
    prefix = str(text or "").split(";", 1)[0]
    mime_type = prefix[5:].strip().lower() if prefix.lower().startswith("data:") else "unknown"
    return f"[redacted:data-url:{mime_type or 'unknown'}]"


def _sanitize_langsmith_metadata_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize_langsmith_metadata_value(item)
            for key, item in value.items()
            if item not in (None, "", [], {})
        }
    if isinstance(value, (list, tuple, set)):
        return [
            _sanitize_langsmith_metadata_value(item)
            for item in value
            if item not in (None, "", [], {})
        ]
    if isinstance(value, str):
        if value.lower().startswith("data:"):
            return "[redacted:data-url]"
        limit = get_langsmith_max_text_chars()
        if len(value) <= limit:
            return value
        return f"{value[: max(1, limit - 3)]}..."
    return value


def sanitize_langsmith_text(
    text: str,
    *,
    capture_text: bool,
    field_name: str = "",
) -> str:
    normalized_field = str(field_name or "").strip().lower()
    if text.lower().startswith("data:"):
        return _redacted_data_url(text)
    if normalized_field in {"url", "urls", "image_url", "base64"} and not capture_text:
        return "[redacted:url]"
    if normalized_field in _SAFE_LANGSMITH_FIELDS:
        return _sanitize_langsmith_metadata_value(text)
    if not capture_text and text:
        return "[redacted]"
    return _sanitize_langsmith_metadata_value(text)


def sanitize_langsmith_value(
    value: Any,
    *,
    capture_text: bool,
    field_name: str = "",
) -> Any:
    if hasattr(value, "model_dump") and callable(getattr(value, "model_dump", None)):
        value = value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {
            str(key): sanitize_langsmith_value(item, capture_text=capture_text, field_name=str(key))
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, (list, tuple, set)):
        return [
            sanitize_langsmith_value(item, capture_text=capture_text, field_name=field_name)
            for item in value
        ]
    if isinstance(value, str):
        return sanitize_langsmith_text(value, capture_text=capture_text, field_name=field_name)
    return _serialize_langsmith_value(value)


def sanitize_langsmith_input(
    value: Any,
    *,
    field_name: str = "",
) -> Any:
    from app.shared.infra.observability.scope import langsmith_capture_inputs_enabled

    return sanitize_langsmith_value(
        value,
        capture_text=langsmith_capture_inputs_enabled(),
        field_name=field_name,
    )


def sanitize_langsmith_output(
    value: Any,
    *,
    field_name: str = "",
) -> Any:
    from app.shared.infra.observability.scope import langsmith_capture_outputs_enabled

    return sanitize_langsmith_value(
        value,
        capture_text=langsmith_capture_outputs_enabled(),
        field_name=field_name,
    )


__all__ = [
    "get_langsmith_max_text_chars",
    "sanitize_langsmith_input",
    "sanitize_langsmith_output",
    "sanitize_langsmith_text",
    "sanitize_langsmith_value",
]
