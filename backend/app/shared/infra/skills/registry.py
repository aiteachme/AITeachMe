"""Registry for external SKILL.md style skillpacks."""

from __future__ import annotations

from app.shared.infra.skills.loader import load_all_skill_definitions
from app.shared.infra.skills.models import SkillpackDefinition


class SkillpackRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, SkillpackDefinition] = {}

    def refresh(self) -> None:
        self._definitions = {
            definition.name: definition
            for definition in load_all_skill_definitions()
        }

    def list_all(self) -> list[SkillpackDefinition]:
        if not self._definitions:
            self.refresh()
        return list(self._definitions.values())

    def get(self, name: str) -> SkillpackDefinition | None:
        if not self._definitions:
            self.refresh()
        return self._definitions.get(name)


_registry: SkillpackRegistry | None = None


def get_skillpack_registry() -> SkillpackRegistry:
    global _registry
    if _registry is None:
        _registry = SkillpackRegistry()
    return _registry


__all__ = [
    "SkillpackRegistry",
    "get_skillpack_registry",
]
