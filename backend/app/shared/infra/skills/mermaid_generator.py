"""Mermaid placeholder generation."""

from __future__ import annotations

import re

from app.shared.infra.config import get_settings
from app.shared.infra.model_router import TaskType
from app.shared.infra.skills.base import BaseSkill, SkillResult
from app.workflows.digest.prompts import build_docgen_mermaid_prompt

_PLACEHOLDER_PATTERN = re.compile(r"<!--\s*\[MERMAID:\s*(.+?)\]\s*-->")


class MermaidGenerator(BaseSkill):
    async def execute(self, *, topic: str, context: str = "") -> SkillResult:
        settings = get_settings()
        if not settings.mermaid_generation_enabled:
            return SkillResult(content=f"```mermaid\n{self._fallback_mermaid(topic, context)}\n```")

        llm = self.context.resolve_llm_caller()
        llm_kwargs = {}
        if (settings.mermaid_generation_model or "").strip():
            llm_kwargs["model"] = f"openai/{settings.mermaid_generation_model.strip()}"
        try:
            response = await llm(
                [{"role": "user", "content": build_docgen_mermaid_prompt(topic=topic, context=context)}],
                task_type=TaskType.DOCGEN_LIGHT,
                tier="fast",
                extra_metadata=self.context.trace_metadata(chapter_index=self.context.chapter_index),
                **llm_kwargs,
            )
            body = str(response).strip().strip("`")
            if not body.lower().startswith("mindmap"):
                body = self._fallback_mermaid(topic, context)
        except Exception:
            body = self._fallback_mermaid(topic, context)
        return SkillResult(content=f"```mermaid\n{body}\n```")

    async def process_placeholders(self, markdown: str) -> str:
        output = markdown
        for placeholder in _PLACEHOLDER_PATTERN.findall(markdown):
            result = await self.run(topic=placeholder, context=markdown)
            output = output.replace(f"<!-- [MERMAID: {placeholder}] -->", result.content)
        return output

    def _fallback_mermaid(self, topic: str, context: str) -> str:
        keywords = [token.strip() for token in re.split(r"[,:;\n]", context) if token.strip()]
        nodes = keywords[:4] if keywords else ["核心概念", "方法步骤", "典型例子"]
        lines = ["mindmap", f"  root(({topic}))"]
        for node in nodes:
            lines.append(f"    {node[:48]}")
        return "\n".join(lines)


__all__ = ["MermaidGenerator"]
