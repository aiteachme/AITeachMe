"""Public API for external SKILL.md style skillpacks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import structlog

from app.shared.infra.skills.registry import get_skillpack_registry

logger = structlog.get_logger(__name__)


def _normalize_selected_skillpacks(selected_skillpacks: Sequence[str] | None) -> list[str]:
    if selected_skillpacks is None:
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in selected_skillpacks:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned


def resolve_skillpacks(
    selected_skillpacks: Sequence[str] | None,
    *,
    prompt_scope: str | None = None,
):
    registry = get_skillpack_registry()
    definitions = []
    for name in _normalize_selected_skillpacks(selected_skillpacks):
        definition = registry.get(name)
        if definition is None:
            logger.warning("skillpack_missing", name=name, prompt_scope=prompt_scope)
            continue
        if not definition.matches_prompt_scope(prompt_scope):
            continue
        definitions.append(definition)
    return definitions


def list_skills(*, prompt_scope: str | None = None) -> list[dict]:
    registry = get_skillpack_registry()
    return [
        definition.to_dict()
        for definition in registry.list_all()
        if definition.matches_prompt_scope(prompt_scope)
    ]


def get_skill(name: str, *, prompt_scope: str | None = None) -> dict:
    registry = get_skillpack_registry()
    definition = registry.get(name)
    if definition is None or not definition.matches_prompt_scope(prompt_scope):
        available = [item["name"] for item in list_skills(prompt_scope=prompt_scope)]
        raise ValueError(f"Skill `{name}` 未找到。可用：{available}")
    return definition.to_dict()


def render_skill(name: str, **kwargs) -> str:
    registry = get_skillpack_registry()
    definition = registry.get(name)
    if definition is None:
        available = [item["name"] for item in list_skills()]
        raise ValueError(f"Skill `{name}` 未找到。可用：{available}")
    return definition.render(**kwargs)


def collect_skillpack_defaults(
    selected_skillpacks: Sequence[str] | None,
    *,
    prompt_scope: str | None = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for definition in resolve_skillpacks(selected_skillpacks, prompt_scope=prompt_scope):
        merged.update(definition.defaults)
    return merged


def collect_recommended_tool_tags(
    selected_skillpacks: Sequence[str] | None,
    *,
    prompt_scope: str | None = None,
) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for definition in resolve_skillpacks(selected_skillpacks, prompt_scope=prompt_scope):
        for tag in definition.recommended_tool_tags:
            normalized = str(tag or "").strip()
            if not normalized:
                continue
            key = normalized.casefold()
            if key in seen:
                continue
            seen.add(key)
            tags.append(normalized)
    return tags


def render_prompt_scoped_skillpacks(
    selected_skillpacks: Sequence[str] | None,
    *,
    prompt_scope: str | None = None,
    bindings: Mapping[str, Any] | None = None,
) -> str:
    rendered: list[str] = []
    for definition in resolve_skillpacks(selected_skillpacks, prompt_scope=prompt_scope):
        try:
            rendered.append(definition.render(**dict(bindings or {})).strip())
        except ValueError as exc:
            logger.warning(
                "skillpack_render_skipped",
                name=definition.name,
                prompt_scope=prompt_scope,
                error=str(exc),
            )
    if not rendered:
        return ""
    return "\n\n".join(rendered).strip()


async def run_skill(name: str, **kwargs) -> str:
    """Compatibility alias for rendering a skillpack into prompt instructions."""

    return render_skill(name, **kwargs)


__all__ = [
    "collect_recommended_tool_tags",
    "collect_skillpack_defaults",
    "get_skill",
    "list_skills",
    "render_prompt_scoped_skillpacks",
    "render_skill",
    "resolve_skillpacks",
    "run_skill",
]
