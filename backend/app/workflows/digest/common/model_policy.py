"""Shared helpers for digest workflow model-policy modules."""

from __future__ import annotations

from collections.abc import Mapping


def compact_metadata(*parts: Mapping[str, object] | None, **metadata: object) -> dict[str, object]:
    """Merge metadata parts and drop empty values before sending them to tracing."""

    compacted: dict[str, object] = {}
    for part in parts:
        if not part:
            continue
        compacted.update(
            {key: value for key, value in part.items() if value not in (None, "", [], {})}
        )
    compacted.update(
        {key: value for key, value in metadata.items() if value not in (None, "", [], {})}
    )
    return compacted


__all__ = ["compact_metadata"]
