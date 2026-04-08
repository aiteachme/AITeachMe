"""Image placeholder handling."""

from __future__ import annotations

import re

from app.shared.infra.config import get_settings
from app.shared.infra.skills.base import BaseSkill, SkillResult

_PLACEHOLDER_PATTERN = re.compile(r"<!--\s*\[IMAGE:\s*(.+?)\]\s*-->")


class ImageGenerator(BaseSkill):
    async def execute(self, *, description: str) -> SkillResult:
        settings = get_settings()
        if not settings.enable_image_generation:
            return SkillResult(content=f"> [!NOTE]\n> 建议配图：{description}")
        return SkillResult(content=f"> [!NOTE]\n> 建议配图：{description}")

    async def process_placeholders(self, markdown: str) -> str:
        output = markdown
        for placeholder in _PLACEHOLDER_PATTERN.findall(markdown):
            result = await self.run(description=placeholder)
            output = output.replace(f"<!-- [IMAGE: {placeholder}] -->", result.content)
        return output


__all__ = ["ImageGenerator"]
