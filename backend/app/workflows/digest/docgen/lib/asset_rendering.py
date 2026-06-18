"""Workflow-local asset placeholder rendering for digest DocGen enrichment."""

from __future__ import annotations

import re

from app.shared.infra.execution import BaseTracedExecution, TracedExecutionContext, TracedExecutionResult
from app.shared.infra.tools.builtin.markdown_processing import sanitize_mermaid_source
from app.workflows.digest.docgen.lib.asset_requests import (
    AssetRequest,
    replace_asset_requests_with_results,
    strip_asset_requests,
)
from app.workflows.digest.docgen.lib.model_policy import DocGenModelStep, docgen_completion_kwargs_with_metadata
from app.workflows.digest.docgen.prompts.generation import build_docgen_mermaid_prompt

_MERMAID_LANG_PATTERN = (
    r"mermaid|mindmap|graph|flowchart|sequenceDiagram|classDiagram|"
    r"stateDiagram(?:-v2)?|erDiagram|gantt|pie|journey|timeline|gitGraph"
)
_MERMAID_FENCE_BLOCK_RE = re.compile(
    rf"```\s*(?:{_MERMAID_LANG_PATTERN})\s*\n(?P<body>.*?)```",
    re.IGNORECASE | re.DOTALL,
)
_GENERIC_FENCE_BLOCK_RE = re.compile(r"```\s*\n(?P<body>.*?)```", re.IGNORECASE | re.DOTALL)
_MINDMAP_ROOT_RE = re.compile(r"^root\(\((.+)\)\)$", re.IGNORECASE)
_MERMAID_KEYWORD_RE = re.compile(
    r"^(mindmap|graph|flowchart|sequenceDiagram|classDiagram|stateDiagram(?:-v2)?|erDiagram|gantt|pie|journey|timeline|gitGraph)\b",
    re.IGNORECASE,
)
_MINDMAP_MIXED_SYNTAX_RE = re.compile(
    r"(-->|==>|\b(?:graph|flowchart|sequencediagram|classdiagram|statediagram|erdiagram|gantt)\b)",
    re.IGNORECASE,
)
_FLOWCHART_HEADER_RE = re.compile(r"^(?:flowchart|graph)\b", re.IGNORECASE)


class MermaidSkipped(ValueError):
    """Raised when the model deliberately decides a diagram is unnecessary."""


def _normalize_mermaid_text(value: str) -> str:
    return str(value or "").replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _sanitize_mindmap_label(value: str, *, max_length: int = 24) -> str:
    cleaned = re.sub(
        r"\b(?:mindmap|root|graph|flowchart|subgraph|classDef|class|style|click|section|title|LR|RL|TB|BT)\b",
        " ",
        str(value or ""),
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"[`#$<>{}\[\]]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_length].rstrip("：:，,。；; ")


def _is_markdown_context_echo_line(line: str) -> bool:
    stripped = str(line or "").strip()
    if not stripped:
        return False
    if stripped.startswith(("```", "#", ">", "|")):
        return True
    if stripped in {"---", "***", "___"}:
        return True
    if re.match(r"^[-*+]\s+\S", stripped) or re.match(r"^\d+\.\s+\S", stripped):
        return True
    return False


def _extract_mermaid_body(response: str) -> str:
    text = _normalize_mermaid_text(response)
    fence_match = _MERMAID_FENCE_BLOCK_RE.search(text)
    if fence_match is not None:
        return _normalize_mermaid_text(fence_match.group("body"))
    generic_match = _GENERIC_FENCE_BLOCK_RE.search(text)
    if generic_match is not None:
        body = _normalize_mermaid_text(generic_match.group("body"))
        first_line = next((line.strip() for line in body.splitlines() if line.strip()), "")
        if _MERMAID_KEYWORD_RE.match(first_line):
            return body
    return text.strip("`").strip()


def _looks_like_mermaid_source(text: str) -> bool:
    body = _extract_mermaid_body(text)
    first_line = next((line.strip() for line in body.splitlines() if line.strip()), "")
    if _MERMAID_KEYWORD_RE.match(first_line):
        return True
    return any(token in body for token in ("-->", "==>"))


def _sanitize_mermaid_body(body: str, *, topic: str) -> str:
    normalized = _extract_mermaid_body(body)
    lines = [
        line.rstrip()
        for line in normalized.splitlines()
        if line.strip()
    ]
    if not lines:
        raise MermaidSkipped("Mermaid model decided this topic does not need a diagram.")
    lines = _trim_context_echo_lines(lines)
    if not lines:
        raise MermaidSkipped("Mermaid model only returned echoed context.")
    first_line = lines[0].strip()
    if first_line.lower().startswith("mindmap"):
        sanitized = _sanitize_mindmap_body("\n".join(lines), topic=topic)
        if not sanitized.strip():
            raise ValueError("Mermaid mindmap content is not usable.")
        return sanitized
    if _FLOWCHART_HEADER_RE.match(first_line) or any(token in "\n".join(lines) for token in ("-->", "==>")):
        sanitized = _sanitize_flowchart_body("\n".join(lines), topic=topic)
        if not sanitized.strip():
            raise ValueError("Mermaid flowchart content is not usable.")
        return sanitized
    raise ValueError("Mermaid model did not return a supported diagram.")


def _trim_context_echo_lines(lines: list[str]) -> list[str]:
    trimmed: list[str] = []
    for index, line in enumerate(lines):
        if index > 0 and _is_markdown_context_echo_line(line):
            break
        trimmed.append(line)
    return trimmed


def _sanitize_mindmap_body(body: str, *, topic: str) -> str:
    del topic
    normalized = _extract_mermaid_body(body)
    if not normalized.lower().startswith("mindmap"):
        return ""

    raw_lines = normalized.splitlines()
    body_lines = [line for line in raw_lines[1:] if line.strip()]
    if any(_MINDMAP_MIXED_SYNTAX_RE.search(line) for line in body_lines):
        return ""

    output = ["mindmap"]
    has_root = False
    child_count = 0
    for raw_line in body_lines:
        if _is_markdown_context_echo_line(raw_line):
            continue
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
        child_count += 1
        if child_count >= 8:
            break

    if not has_root:
        return ""
    return "\n".join(output)


def _sanitize_flowchart_body(body: str, *, topic: str) -> str:
    del topic
    normalized = _extract_mermaid_body(body)
    sanitized = sanitize_mermaid_source(normalized)
    return sanitized.strip()


class _MermaidPlaceholderRuntime(BaseTracedExecution):
    @property
    def trace_namespace(self) -> str:
        return "DocGen资产"

    @property
    def trace_name(self) -> str:
        return "图示占位处理"

    async def execute(self, *, topic: str, context: str = "") -> TracedExecutionResult:
        if _looks_like_mermaid_source(topic):
            raw_body = _extract_mermaid_body(topic)
            body = _sanitize_mermaid_body(topic, topic=topic)
            return TracedExecutionResult(
                content=f"```mermaid\n{body}\n```",
                metadata={
                    "from_raw_placeholder": True,
                    "sanitized": raw_body.strip() != body.strip(),
                    "body_preview": body[:240],
                },
            )

        llm = self.context.resolve_llm_caller()
        try:
            response = await llm(
                [{"role": "user", "content": build_docgen_mermaid_prompt(topic=topic, context=context)}],
                **docgen_completion_kwargs_with_metadata(
                    DocGenModelStep.MERMAID_PLACEHOLDER,
                    digest_mode=self.context.digest_mode,
                    extra_metadata=self.context.trace_metadata(chapter_index=self.context.chapter_index),
                ),
            )
            raw_body = _extract_mermaid_body(str(response))
            body = _sanitize_mermaid_body(str(response), topic=topic)
        except MermaidSkipped as exc:
            return TracedExecutionResult(
                content="",
                metadata={
                    "fallback_used": False,
                    "skipped": True,
                    "skip_reason": str(exc)[:240],
                },
            )
        except Exception as exc:
            raise RuntimeError(f"Mermaid placeholder rendering failed: {str(exc)[:240]}") from exc
        return TracedExecutionResult(
            content=f"```mermaid\n{body}\n```",
            metadata={
                "fallback_used": False,
                "sanitized": raw_body.strip() != body.strip(),
                "body_preview": body[:240],
            },
        )

    async def process_placeholders(self, markdown: str) -> str:
        processed, _reports = await self.process_placeholders_with_reports(markdown)
        return processed

    async def process_placeholders_with_reports(self, markdown: str) -> tuple[str, list[dict[str, object]]]:
        async def render(request: AssetRequest) -> tuple[str, dict[str, object]]:
            result = await self.run(topic=request.description, context=markdown)
            metadata = dict(result.metadata or {})
            report = (
                {
                    "source_placeholder": request.description,
                    "fallback_used": bool(metadata.get("fallback_used", False)),
                    "from_raw_placeholder": bool(metadata.get("from_raw_placeholder", False)),
                    "skipped": bool(metadata.get("skipped", False)),
                    "skip_reason": str(metadata.get("skip_reason") or "")[:240],
                    "sanitized": bool(metadata.get("sanitized", False)),
                    "error": str(metadata.get("error") or "")[:240],
                    "body_preview": str(metadata.get("body_preview") or "")[:240],
                }
            )
            return result.content, report

        processed, reports = await replace_asset_requests_with_results(markdown, kind="mermaid", renderer=render)
        return processed, reports

class DocGenAssetRuntime:
    def __init__(self, context: TracedExecutionContext) -> None:
        self.context = context

    async def process_mermaid_placeholders(self, markdown: str) -> str:
        generator = _MermaidPlaceholderRuntime(self.context)
        return await generator.process_placeholders(markdown)

    async def process_mermaid_placeholders_with_reports(self, markdown: str) -> tuple[str, list[dict[str, object]]]:
        generator = _MermaidPlaceholderRuntime(self.context)
        return await generator.process_placeholders_with_reports(markdown)

    async def process_interactive_placeholders(self, markdown: str, *, digest_mode: str = "") -> str:
        del digest_mode
        return strip_asset_requests(markdown, kinds={"interactive"})


__all__ = ["DocGenAssetRuntime"]
