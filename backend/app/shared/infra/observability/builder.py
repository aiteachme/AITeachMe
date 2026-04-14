"""LangSmith metadata and tag building helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.shared.infra.observability.sanitize import _sanitize_langsmith_metadata_value
from app.shared.infra.runtime import get_app_version


def build_langsmith_metadata(
    *,
    subject: str = "",
    build_session_id: str = "",
    workflow: str = "",
    lane: str = "",
    node: str = "",
    extra_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a normalized LangSmith metadata payload."""

    metadata: dict[str, Any] = {
        "app": "aiteachme-backend",
        "app_version": get_app_version(),
    }
    if subject:
        metadata["subject"] = subject
    if build_session_id:
        metadata["build_session_id"] = build_session_id
    if workflow:
        metadata["workflow"] = workflow
    if lane:
        metadata["lane"] = lane
    if node:
        metadata["node"] = node
    if extra_metadata:
        metadata.update(
            {
                str(key): _sanitize_langsmith_metadata_value(value)
                for key, value in extra_metadata.items()
                if value not in (None, "", [], {})
            }
        )
    return metadata


def build_langsmith_tags(
    *,
    workflow: str = "",
    lane: str = "",
    node: str = "",
    extra_tags: list[str] | None = None,
) -> list[str]:
    """Build a stable LangSmith tag list."""

    tags = ["aiteachme"]
    if workflow:
        tags.append(f"workflow:{workflow}")
    if lane:
        tags.append(f"lane:{lane}")
    if node:
        tags.append(f"node:{node}")
    if extra_tags:
        tags.extend(tag for tag in extra_tags if tag)
    return list(dict.fromkeys(tags))


def build_langsmith_extra(
    *,
    subject: str = "",
    build_session_id: str = "",
    workflow: str = "",
    lane: str = "",
    node: str = "",
    extra_metadata: Mapping[str, Any] | None = None,
    extra_tags: list[str] | None = None,
) -> dict[str, Any] | None:
    """Build one ``langsmith_extra`` payload for ``@traceable`` calls."""

    from app.shared.infra.observability.scope import langsmith_tracing_enabled

    if not langsmith_tracing_enabled():
        return None

    project_name, metadata, tags = _build_langsmith_context(
        subject=subject,
        build_session_id=build_session_id,
        workflow=workflow,
        lane=lane,
        node=node,
        extra_metadata=extra_metadata,
        extra_tags=extra_tags,
    )
    extra: dict[str, Any] = {
        "metadata": metadata,
        "tags": tags,
    }
    if project_name:
        extra["project_name"] = project_name
    return extra


def _build_langsmith_context(
    *,
    subject: str = "",
    build_session_id: str = "",
    workflow: str = "",
    lane: str = "",
    node: str = "",
    extra_metadata: Mapping[str, Any] | None = None,
    extra_tags: list[str] | None = None,
) -> tuple[str | None, dict[str, Any], list[str]]:
    from app.shared.infra.observability.scope import get_langsmith_project_name

    project_name = get_langsmith_project_name()
    metadata = build_langsmith_metadata(
        subject=subject,
        build_session_id=build_session_id,
        workflow=workflow,
        lane=lane,
        node=node,
        extra_metadata=extra_metadata,
    )
    tags = build_langsmith_tags(
        workflow=workflow,
        lane=lane,
        node=node,
        extra_tags=extra_tags,
    )
    return project_name, metadata, tags


__all__ = [
    "build_langsmith_extra",
    "build_langsmith_metadata",
    "build_langsmith_tags",
]
