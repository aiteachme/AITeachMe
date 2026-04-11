"""Workflow-local asset runtime for digest DocGen enrichment."""

from __future__ import annotations

import re

from app.shared.infra.config import get_settings
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.traced_execution import BaseTracedExecution, TracedExecutionContext, TracedExecutionResult
from app.workflows.digest.prompts import build_docgen_mermaid_prompt

_IMAGE_PLACEHOLDER_PATTERN = re.compile(r"<!--\s*\[IMAGE:\s*(.+?)\]\s*-->")
_MERMAID_PLACEHOLDER_PATTERN = re.compile(r"<!--\s*\[MERMAID:\s*(.+?)\]\s*-->")
_INTERACTIVE_PLACEHOLDER_PATTERN = re.compile(r"<!--\s*\[INTERACTIVE:\s*(.+?)\]\s*-->")


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


class _InteractivePlaceholderRuntime(BaseTracedExecution):
    @property
    def trace_namespace(self) -> str:
        return "workflow_runtime.docgen.assets"

    @property
    def trace_name(self) -> str:
        return "interactive_placeholder"

    async def execute(self, *, description: str, context: str = "", digest_mode: str = "") -> TracedExecutionResult:
        template_kind = self._resolve_template_kind(description=description, digest_mode=digest_mode)
        if template_kind == "formula_expander":
            content = self._build_formula_expander(description=description, context=context)
        else:
            content = self._build_concept_check(description=description, context=context)
        return TracedExecutionResult(
            content=content,
            metadata={
                "template_kind": template_kind,
                "asset_enabled": True,
            },
        )

    async def process_placeholders(self, markdown: str, *, digest_mode: str = "") -> str:
        output = markdown
        for placeholder in _INTERACTIVE_PLACEHOLDER_PATTERN.findall(markdown):
            result = await self.run(description=placeholder, context=markdown, digest_mode=digest_mode)
            output = output.replace(f"<!-- [INTERACTIVE: {placeholder}] -->", result.content)
        return output

    def _resolve_template_kind(self, *, description: str, digest_mode: str) -> str:
        text = f"{description} {digest_mode}".lower()
        if any(marker in text for marker in ("公式", "推导", "证明", "derivation", "formula")):
            return "formula_expander"
        return "concept_check"

    def _build_formula_expander(self, *, description: str, context: str) -> str:
        bullets = self._extract_context_points(context, limit=4) or [
            "先明确这一步在连接哪个定义或公式。",
            "再判断每一步变形是否满足成立条件。",
            "最后把结论和题型或应用场景对应起来。",
        ]
        items = "\n".join(f"      <li>{item}</li>" for item in bullets)
        return (
            '<div class="atm-interactive-block" data-atm-kind="formula-expander">\n'
            "  <style>\n"
            "    .atm-interactive-block{margin:16px 0;padding:14px 16px;border:1px solid #d8c7a2;border-radius:14px;background:linear-gradient(180deg,#fff8ec 0%,#fffdf8 100%);}\n"
            "    .atm-interactive-block summary{cursor:pointer;font-weight:600;color:#6f4e12;}\n"
            "    .atm-interactive-block ol{margin:10px 0 0 20px;}\n"
            "    .atm-interactive-block code{background:#f3e7cf;padding:1px 6px;border-radius:6px;}\n"
            "  </style>\n"
            f"  <strong>交互推导卡：{description}</strong>\n"
            '  <details open>\n'
            "    <summary>点击展开推导路径</summary>\n"
            "    <p>阅读时建议按“定义 -> 条件 -> 变形 -> 结论”的顺序逐步核对。</p>\n"
            "    <ol>\n"
            f"{items}\n"
            "    </ol>\n"
            "  </details>\n"
            '  <details>\n'
            "    <summary>自检问题</summary>\n"
            "    <p>如果把中间某一步拿掉，你还能解释为什么最后的结论仍然成立吗？</p>\n"
            "  </details>\n"
            "</div>"
        )

    def _build_concept_check(self, *, description: str, context: str) -> str:
        bullets = self._extract_context_points(context, limit=4) or [
            "先说清楚两个概念最核心的区别。",
            "再找一个容易混淆的场景做对比。",
            "最后用一句话总结判断抓手。",
        ]
        cards = "\n".join(
            f'      <li><strong>检查点 {index}：</strong>{item}</li>'
            for index, item in enumerate(bullets, start=1)
        )
        return (
            '<div class="atm-interactive-block" data-atm-kind="concept-check">\n'
            "  <style>\n"
            "    .atm-interactive-block{margin:16px 0;padding:14px 16px;border:1px solid #bfd5c2;border-radius:14px;background:linear-gradient(180deg,#f4fbf4 0%,#fbfffb 100%);}\n"
            "    .atm-interactive-block summary{cursor:pointer;font-weight:600;color:#245a33;}\n"
            "    .atm-interactive-block ul{margin:10px 0 0 20px;}\n"
            "  </style>\n"
            f"  <strong>交互自检卡：{description}</strong>\n"
            '  <details open>\n'
            "    <summary>点击展开概念对比 / 自检提示</summary>\n"
            "    <p>读完这一块以后，不要只觉得“我看懂了”，试着逐条回答下面的问题。</p>\n"
            "    <ul>\n"
            f"{cards}\n"
            "    </ul>\n"
            "  </details>\n"
            '  <details>\n'
            "    <summary>迁移提醒</summary>\n"
            "    <p>把这个概念换到一道新题或另一个例子里，你是否还能快速判断它应该怎么用？</p>\n"
            "  </details>\n"
            "</div>"
        )

    def _extract_context_points(self, context: str, *, limit: int) -> list[str]:
        parts = [
            item.strip(" -")
            for item in re.split(r"[\n。；;]+", str(context or "").strip())
            if item.strip()
            and "[INTERACTIVE:" not in item
            and "[MERMAID:" not in item
            and "[IMAGE:" not in item
            and "<!--" not in item
        ]
        deduped: list[str] = []
        seen: set[str] = set()
        for item in parts:
            key = item.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item[:120])
            if len(deduped) >= limit:
                break
        return deduped


class DocGenAssetRuntime:
    def __init__(self, context: TracedExecutionContext) -> None:
        self.context = context

    async def process_mermaid_placeholders(self, markdown: str) -> str:
        generator = _MermaidPlaceholderRuntime(self.context)
        return await generator.process_placeholders(markdown)

    async def process_image_placeholders(self, markdown: str) -> str:
        generator = _ImagePlaceholderRuntime(self.context)
        return await generator.process_placeholders(markdown)

    async def process_interactive_placeholders(self, markdown: str, *, digest_mode: str = "") -> str:
        generator = _InteractivePlaceholderRuntime(self.context)
        return await generator.process_placeholders(markdown, digest_mode=digest_mode)


__all__ = ["DocGenAssetRuntime"]
