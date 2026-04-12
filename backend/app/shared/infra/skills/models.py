"""Models for external SKILL.md style skillpacks."""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import chain
from typing import Any


@dataclass(slots=True)
class SkillpackParameter:
    name: str
    type: str = "string"
    description: str = ""
    required: bool = False
    default: Any = None


@dataclass(slots=True)
class SkillpackDefinition:
    name: str
    description: str = ""
    version: str = ""
    tags: list[str] = field(default_factory=list)
    prompt_scope: list[str] = field(default_factory=list)
    recommended_tool_tags: list[str] = field(default_factory=list)
    defaults: dict[str, Any] = field(default_factory=dict)
    parameters: list[SkillpackParameter] = field(default_factory=list)
    instructions: str = ""
    source_path: str = ""
    source_kind: str = "skillpack"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "tags": list(self.tags),
            "prompt_scope": list(self.prompt_scope),
            "recommended_tool_tags": list(self.recommended_tool_tags),
            "defaults": dict(self.defaults),
            "parameters": [
                {
                    "name": parameter.name,
                    "type": parameter.type,
                    "description": parameter.description,
                    "required": parameter.required,
                    "default": parameter.default,
                }
                for parameter in self.parameters
            ],
            "source_path": self.source_path,
            "source_kind": self.source_kind,
        }

    def matches_prompt_scope(self, prompt_scope: str | None) -> bool:
        normalized_requested = str(prompt_scope or "").strip().lower()
        if not normalized_requested:
            return True

        allowed_scopes = {
            str(scope or "").strip().lower()
            for scope in self.prompt_scope
            if str(scope or "").strip()
        }
        if not allowed_scopes:
            return True
        if "*" in allowed_scopes or "global" in allowed_scopes:
            return True

        requested_parts = [part for part in normalized_requested.split(".") if part]
        fallback_scopes = {
            normalized_requested,
            *chain(
                (
                    ".".join(requested_parts[:index])
                    for index in range(1, len(requested_parts))
                ),
                (
                    "_".join(requested_parts[:index])
                    for index in range(1, len(requested_parts))
                ),
            ),
        }
        fallback_scopes.discard("")
        return bool(allowed_scopes.intersection(fallback_scopes))

    def render(self, **kwargs: Any) -> str:
        resolved_kwargs: dict[str, Any] = {}
        for parameter in self.parameters:
            if parameter.name in kwargs:
                resolved_kwargs[parameter.name] = kwargs[parameter.name]
                continue
            if parameter.name in self.defaults:
                resolved_kwargs[parameter.name] = self.defaults[parameter.name]
                continue
            if parameter.default is not None:
                resolved_kwargs[parameter.name] = parameter.default
                continue
            if parameter.required:
                raise ValueError(f"Skill `{self.name}` 缺少必填参数 `{parameter.name}`")

        for key, value in kwargs.items():
            resolved_kwargs.setdefault(key, value)

        for key, value in self.defaults.items():
            resolved_kwargs.setdefault(key, value)

        rendered = self.instructions
        for key, value in resolved_kwargs.items():
            rendered = rendered.replace(f"{{{key}}}", str(value))

        lines = [f"# Skill: {self.name}"]
        if self.description:
            lines.extend(["", self.description])
        if resolved_kwargs:
            lines.extend(["", "## Bound Parameters", ""])
            for key, value in resolved_kwargs.items():
                lines.append(f"- {key}: {value}")
        if rendered.strip():
            lines.extend(["", "## Instructions", "", rendered.strip()])
        return "\n".join(lines).strip() + "\n"


__all__ = [
    "SkillpackDefinition",
    "SkillpackParameter",
]
