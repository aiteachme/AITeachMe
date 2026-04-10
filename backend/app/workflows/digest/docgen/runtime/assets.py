"""Workflow-local asset runtime for digest DocGen enrichment."""

from __future__ import annotations

import re

from app.shared.infra.config import get_settings
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.traced_execution import BaseTracedExecution, TracedExecutionContext, TracedExecutionResult
from app.workflows.digest.prompts import build_docgen_mermaid_prompt

_IMAGE_PLACEHOLDER_PATTERN = re.compile(r"<!--\s*\[IMAGE:\s*(.+?)\]\s*-->")
_MERMAID_PLACEHOLDER_PATTERN = re.compile(r"<!--\s*\[MERMAID:\s*(.+?)\]\s*-->")


class _ImagePlaceholderRuntime(BaseTracedExecution):
    @property
    def trace_namespace(self) -> str:
        return "workflow_runtime.docgen.assets"

    @property
    def trace_name(self) -> str:
        return "image_placeholder"

    async def execute(self, *, description: str) -> TracedExecutionResult:
        settings = get_settings()
        model_name = (settings.image_generation_model or "").strip()
        if not settings.image_generation_enabled:
            return TracedExecutionResult(
                content=f"> [!NOTE]\n> 未配置文生图模型，暂以配图建议占位：{description}",
                metadata={"asset_enabled": False},
            )
        return TracedExecutionResult(
            content=f"> [!NOTE]\n> 建议配图：{description}\n>\n> 已配置文生图模型：`{model_name or 'legacy-boolean-enabled'}`",
            metadata={"asset_enabled": True, "model": model_name or None},
        )

    async def process_placeholders(self, markdown: str) -> str:
        output = markdown
        for placeholder in _IMAGE_PLACEHOLDER_PATTERN.findall(markdown):
            result = await self.run(description=placeholder)
            output = output.replace(f"<!-- [IMAGE: {placeholder}] -->", result.content)
        return output


class _MermaidPlaceholderRuntime(BaseTracedExecution):
    @property
    def trace_namespace(self) -> str:
        return "workflow_runtime.docgen.assets"

    @property
    def trace_name(self) -> str:
        return "mermaid_placeholder"

    async def execute(self, *, topic: str, context: str = "") -> TracedExecutionResult:
        settings = get_settings()
        if not settings.mermaid_generation_enabled:
            return TracedExecutionResult(content=f"```mermaid\n{self._fallback_mermaid(topic, context)}\n```")

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
        return TracedExecutionResult(content=f"```mermaid\n{body}\n```")

    async def process_placeholders(self, markdown: str) -> str:
        output = markdown
        for placeholder in _MERMAID_PLACEHOLDER_PATTERN.findall(markdown):
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


class DocGenAssetRuntime:
    def __init__(self, context: TracedExecutionContext) -> None:
        self.context = context

    async def process_mermaid_placeholders(self, markdown: str) -> str:
        generator = _MermaidPlaceholderRuntime(self.context)
        return await generator.process_placeholders(markdown)

    async def process_image_placeholders(self, markdown: str) -> str:
        generator = _ImagePlaceholderRuntime(self.context)
        return await generator.process_placeholders(markdown)


__all__ = ["DocGenAssetRuntime"]
