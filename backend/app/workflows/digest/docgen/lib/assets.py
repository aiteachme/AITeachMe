"""Workflow-local asset runtime for digest DocGen enrichment."""

from __future__ import annotations

import re

from app.shared.infra.settings import get_settings
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.execution import BaseTracedExecution, TracedExecutionContext, TracedExecutionResult
from app.workflows.digest.docgen.prompts import build_docgen_mermaid_prompt

_IMAGE_PLACEHOLDER_PATTERN = re.compile(r"<!--\s*\[IMAGE:\s*(.+?)\]\s*-->", re.IGNORECASE | re.DOTALL)
_MERMAID_PLACEHOLDER_PATTERN = re.compile(r"<!--\s*\[MERMAID:\s*(.+?)\]\s*-->", re.IGNORECASE | re.DOTALL)
_INTERACTIVE_PLACEHOLDER_PATTERN = re.compile(r"<!--\s*\[INTERACTIVE:\s*(.+?)\]\s*-->", re.IGNORECASE | re.DOTALL)
_MERMAID_FENCE_BLOCK_RE = re.compile(r"```(?:mermaid)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_MINDMAP_ROOT_RE = re.compile(r"^root\(\((.+)\)\)$", re.IGNORECASE)
_MINDMAP_MIXED_SYNTAX_RE = re.compile(
    r"(-->|==>|\b(?:graph|flowchart|sequencediagram|classdiagram|statediagram|erdiagram|gantt)\b)",
    re.IGNORECASE,
)


def _normalize_mermaid_text(value: str) -> str:
    return str(value or "").replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _sanitize_mindmap_label(value: str, *, max_length: int = 24) -> str:
    cleaned = re.sub(
        r"\b(?:mindmap|root|graph|flowchart|subgraph|classDef|class|style|click|section|title|LR|RL|TB|BT)\b",
        " ",
        str(value or ""),
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"[`$<>{}\[\]]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_length].rstrip("：:，,。；; ")


def _extract_mermaid_body(response: str) -> str:
    text = _normalize_mermaid_text(response)
    fence_match = _MERMAID_FENCE_BLOCK_RE.search(text)
    if fence_match is not None:
        return _normalize_mermaid_text(fence_match.group(1))
    return text.strip("`").strip()


def _extract_mindmap_labels(text: str, *, limit: int = 6) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()

    def _push(value: str) -> None:
        cleaned = _sanitize_mindmap_label(value)
        if not cleaned:
            return
        key = cleaned.casefold()
        if key in seen:
            return
        seen.add(key)
        labels.append(cleaned)

    for match in re.finditer(r"root\(\((.+?)\)\)", text, re.IGNORECASE):
        _push(match.group(1))
    for match in re.finditer(r"\[([^\]]+)\]", text):
        _push(match.group(1))

    for raw_line in _normalize_mermaid_text(text).splitlines():
        line = raw_line.strip()
        if not line or line.lower() == "mindmap" or line.startswith("```"):
            continue
        root_match = _MINDMAP_ROOT_RE.match(line)
        if root_match is not None:
            _push(root_match.group(1))
            continue
        if _MINDMAP_MIXED_SYNTAX_RE.search(line):
            arrow_bits = re.findall(r"\[([^\]]+)\]", line)
            if arrow_bits:
                for item in arrow_bits:
                    _push(item)
            else:
                _push(line.split("-->")[-1].split("==>")[-1])
            continue
        _push(re.sub(r"^[-*+]\s+", "", line))
        if len(labels) >= limit:
            break

    return labels[:limit]


def _build_simple_mindmap(topic: str, source_text: str) -> str:
    labels = _extract_mindmap_labels(source_text, limit=6)
    root = labels[0] if labels else _sanitize_mindmap_label(topic)
    if not root:
        root = "核心主题"
    lines = ["mindmap", f"  root(({root}))"]
    for label in labels[1:]:
        lines.append(f"    {label}")
    return "\n".join(lines)


async def _replace_placeholders(markdown: str, pattern: re.Pattern[str], renderer) -> str:
    output: list[str] = []
    last_index = 0
    for match in pattern.finditer(markdown):
        output.append(markdown[last_index : match.start()])
        description = str(match.group(1) or "").strip()
        output.append(await renderer(description))
        last_index = match.end()
    output.append(markdown[last_index:])
    return "".join(output)


def _sanitize_mindmap_body(body: str, *, topic: str) -> str:
    normalized = _extract_mermaid_body(body)
    if not normalized.lower().startswith("mindmap"):
        return _build_simple_mindmap(topic, body)

    raw_lines = normalized.splitlines()
    body_lines = [line for line in raw_lines[1:] if line.strip()]
    if any(_MINDMAP_MIXED_SYNTAX_RE.search(line) for line in body_lines):
        return _build_simple_mindmap(topic, normalized)

    output = ["mindmap"]
    has_root = False
    for raw_line in body_lines:
        expanded = raw_line.replace("\t", "  ")
        indent_chars = len(re.match(r"^\s*", expanded).group(0))
        indent_level = max(1, indent_chars // 2)
        stripped = re.sub(r"^[-*+]\s+", "", expanded.strip())
        if not stripped:
            continue

        root_match = _MINDMAP_ROOT_RE.match(stripped)
        if root_match is not None:
            root_label = _sanitize_mindmap_label(root_match.group(1))
            if root_label:
                output.append(f"  root(({root_label}))")
                has_root = True
            continue

        label = _sanitize_mindmap_label(stripped)
        if not label:
            continue
        if not has_root and indent_level <= 1:
            output.append(f"  root(({label}))")
            has_root = True
            continue
        output.append(f"{'  ' * max(2, indent_level)}{label}")

    if not has_root:
        return _build_simple_mindmap(topic, normalized)
    return "\n".join(output)


class _ImagePlaceholderRuntime(BaseTracedExecution):
    @property
    def trace_namespace(self) -> str:
        return "DocGen资产"

    @property
    def trace_name(self) -> str:
        return "图片占位处理"

    async def execute(self, *, description: str) -> TracedExecutionResult:
        settings = get_settings()
        model_name = (settings.models.image_generation or "").strip()
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
        async def render(placeholder: str) -> str:
            result = await self.run(description=placeholder)
            return result.content

        return await _replace_placeholders(markdown, _IMAGE_PLACEHOLDER_PATTERN, render)


class _MermaidPlaceholderRuntime(BaseTracedExecution):
    @property
    def trace_namespace(self) -> str:
        return "DocGen资产"

    @property
    def trace_name(self) -> str:
        return "图示占位处理"

    async def execute(self, *, topic: str, context: str = "") -> TracedExecutionResult:
        settings = get_settings()
        if not settings.mermaid_generation_enabled:
            return TracedExecutionResult(content=f"```mermaid\n{self._fallback_mermaid(topic, context)}\n```")

        llm = self.context.resolve_llm_caller()
        llm_kwargs = {}
        if (settings.models.mermaid_generation or "").strip():
            llm_kwargs["model"] = settings.models.mermaid_generation.strip()
        try:
            response = await llm(
                [{"role": "user", "content": build_docgen_mermaid_prompt(topic=topic, context=context)}],
                task_type=TaskType.DOCGEN_LIGHT,
                model="light",
                extra_metadata=self.context.trace_metadata(chapter_index=self.context.chapter_index),
                **llm_kwargs,
            )
            body = _sanitize_mindmap_body(str(response), topic=topic)
        except Exception as exc:
            body = self._fallback_mermaid(topic, context)
            return TracedExecutionResult(
                content=f"```mermaid\n{body}\n```",
                metadata={"fallback_used": True, "error": str(exc)[:240]},
            )
        return TracedExecutionResult(content=f"```mermaid\n{body}\n```", metadata={"fallback_used": False})

    async def process_placeholders(self, markdown: str) -> str:
        async def render(placeholder: str) -> str:
            result = await self.run(topic=placeholder, context=markdown)
            return result.content

        return await _replace_placeholders(markdown, _MERMAID_PLACEHOLDER_PATTERN, render)

    def _fallback_mermaid(self, topic: str, context: str) -> str:
        fallback_source = "\n".join(
            [topic, *[token.strip() for token in re.split(r"[,:;\n]", context) if token.strip()][:4]]
        )
        return _build_simple_mindmap(topic, fallback_source)


class _InteractivePlaceholderRuntime(BaseTracedExecution):
    @property
    def trace_namespace(self) -> str:
        return "DocGen资产"

    @property
    def trace_name(self) -> str:
        return "交互块占位处理"

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
        async def render(placeholder: str) -> str:
            result = await self.run(description=placeholder, context=markdown, digest_mode=digest_mode)
            return result.content

        return await _replace_placeholders(markdown, _INTERACTIVE_PLACEHOLDER_PATTERN, render)

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
