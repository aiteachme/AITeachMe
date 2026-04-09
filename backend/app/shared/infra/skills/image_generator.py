"""Image placeholder handling."""

from __future__ import annotations

import re

from app.shared.infra.config import get_settings
from app.shared.infra.skills.base import BaseSkill, SkillResult

_PLACEHOLDER_PATTERN = re.compile(r"<!--\s*\[IMAGE:\s*(.+?)\]\s*-->")


class ImageGenerator(BaseSkill):
    async def execute(self, *, description: str) -> SkillResult:
        settings = get_settings()
        model_name = (settings.image_generation_model or "").strip()
        if not settings.image_generation_enabled:
            return SkillResult(
                content=f"> [!NOTE]\n> 未配置文生图模型，暂以配图建议占位：{description}",
                metadata={"capability_enabled": False},
            )
        # 当前流水线仍以“配图占位 + 提示词”方式落地，后续再接真实图片生成接口。
        return SkillResult(
            content=f"> [!NOTE]\n> 建议配图：{description}\n>\n> 已配置文生图模型：`{model_name or 'legacy-boolean-enabled'}`",
            metadata={"capability_enabled": True, "model": model_name or None},
        )

    async def process_placeholders(self, markdown: str) -> str:
        output = markdown
        for placeholder in _PLACEHOLDER_PATTERN.findall(markdown):
            result = await self.run(description=placeholder)
            output = output.replace(f"<!-- [IMAGE: {placeholder}] -->", result.content)
        return output


__all__ = ["ImageGenerator"]
