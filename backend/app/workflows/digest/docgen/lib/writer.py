"""Workflow-local writer runtime for digest DocGen."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from time import perf_counter
from typing import Any

from app.shared.infra.env_support import get_env_bounded_float, get_env_bounded_int
from app.shared.infra.execution import BaseTracedExecution, TracedExecutionResult
from app.shared.infra.llm_support import acompletion_stream, run_llm_tasks
from app.shared.infra.tools.builtin.markdown_processing import count_words
from app.workflows.digest.common.pedagogy import (
    analyze_chapter_heading_quality,
    resolve_effective_chapter_title,
)
from app.workflows.digest.docgen.prompts.generation import (
    build_docgen_heading_repair_messages,
    build_docgen_writer_messages,
)
from app.workflows.digest.docgen.lib.asset_requests import (
    ASSET_REQUEST_LANGUAGE,
    build_asset_request_block,
    has_asset_request,
    strip_asset_requests,
)
from app.workflows.digest.docgen.lib.model_policy import DocGenModelStep, docgen_completion_kwargs_with_metadata
from app.workflows.digest.docgen.lib.presentation_policy import (
    find_docgen_presentation_issues,
    normalize_docgen_presentation,
    summarize_docgen_presentation,
)

_PLACEHOLDER_TOKEN_MAP = {
    "asset_request": ASSET_REQUEST_LANGUAGE,
}

STREAM_CALLBACK_MIN_DELTA_CHARS = get_env_bounded_int(
    "DOCGEN_WRITER_STREAM_CALLBACK_MIN_DELTA_CHARS",
    32,
    min_value=8,
    max_value=200,
)
STREAM_CALLBACK_MIN_INTERVAL_S = get_env_bounded_float(
    "DOCGEN_WRITER_STREAM_CALLBACK_MIN_INTERVAL_S",
    0.12,
    min_value=0.03,
    max_value=1.0,
)


class DocGenWriterRuntime(BaseTracedExecution):
    @property
    def trace_namespace(self) -> str:
        return "DocGen"

    @property
    def trace_name(self) -> str:
        return "章节写作"

    async def execute(
        self,
        *,
        chapter_plan: Mapping[str, Any],
        dense_context: str,
        digest_mode: str,
        on_stream_update: Callable[[str], Awaitable[None]] | None = None,
    ) -> TracedExecutionResult:
        """根据章节执行合同和 dense_context 生成学生可读草稿。

        Writer 只负责把研究材料写成一章 Markdown：先调用主模型生成正文，
        再执行标题、结构、字数和学生可见内容清理。事实检索和证据账本不在
        这里做，避免写作器越权补知识。
        """

        llm = self.context.resolve_llm_caller()
        title = resolve_effective_chapter_title(chapter_plan, fallback_title="Untitled Chapter")
        objective = str(chapter_plan.get("objective") or "")
        required_elements = [str(item) for item in chapter_plan.get("required_elements", []) if str(item).strip()]
        writing_instructions = str(chapter_plan.get("writing_instructions") or "")
        media_hints = chapter_plan.get("media_hints") or {}
        execution_contract = dict(chapter_plan.get("execution_contract") or {})
        source_count = len(list(chapter_plan.get("source_details") or []))
        chapter_index = int(chapter_plan.get("chapter_index", 0) or 0) or None
        chapter_count = int(chapter_plan.get("total_chapters", 0) or 0) or None
        messages = build_docgen_writer_messages(
            title=title,
            objective=objective,
            digest_mode=digest_mode,
            required_elements=required_elements,
            writing_instructions=writing_instructions,
            source_count=source_count,
            dense_context=dense_context,
            chapter_index=chapter_index,
            chapter_count=chapter_count,
            execution_contract=execution_contract,
        )
        writer_model_kwargs = docgen_completion_kwargs_with_metadata(
            DocGenModelStep.WRITER,
            digest_mode=digest_mode,
            extra_metadata=self.context.trace_metadata(chapter_index=self.context.chapter_index),
        )
        markdown = ""
        if on_stream_update is not None and self.context.llm_caller is None:
            streamed_chars = 0

            async def _run_writer_stream(_: object) -> str:
                nonlocal streamed_chars
                chunks: list[str] = []
                stream_callback_last_at = perf_counter()
                stream_callback_last_len = 0
                async for chunk in acompletion_stream(
                    messages,
                    **writer_model_kwargs,
                ):
                    chunk_text = str(chunk)
                    if not chunk_text:
                        continue
                    chunks.append(chunk_text)
                    streamed_chars += len(chunk_text)
                    now = perf_counter()
                    if (
                        streamed_chars - stream_callback_last_len >= STREAM_CALLBACK_MIN_DELTA_CHARS
                        or now - stream_callback_last_at >= STREAM_CALLBACK_MIN_INTERVAL_S
                    ):
                        stream_callback_last_at = now
                        stream_callback_last_len = streamed_chars
                        await self._safe_stream_update(on_stream_update, "".join(chunks))
                result = "".join(chunks)
                await self._safe_stream_update(on_stream_update, result)
                return result

            try:
                (markdown,) = await run_llm_tasks([None], _run_writer_stream, max_concurrent=1)
            except Exception as exc:
                self.logger.warning(
                    "docgen_writer_stream_failed_falling_back",
                    chapter_index=chapter_index,
                    streamed_chars=streamed_chars,
                    error=str(exc),
                )

        if not markdown.strip():
            async def _run_writer_completion(_: object) -> str:
                return str(await llm(messages, **writer_model_kwargs) or "")

            (markdown,) = await run_llm_tasks([None], _run_writer_completion, max_concurrent=1)

        markdown = strip_asset_requests(str(markdown).strip())
        heading_quality = analyze_chapter_heading_quality(
            markdown,
            digest_mode=digest_mode,
        )
        heading_repair_applied = False
        if bool(heading_quality.get("needs_agent_repair")):
            repaired_markdown = await self._repair_heading_structure(
                title=title,
                objective=objective,
                digest_mode=digest_mode,
                required_elements=required_elements,
                writing_instructions=writing_instructions,
                source_count=source_count,
                markdown=markdown,
                dense_context=dense_context,
                chapter_index=chapter_index,
                chapter_count=chapter_count,
            )
            if repaired_markdown:
                markdown = repaired_markdown
                heading_repair_applied = True
                heading_quality = analyze_chapter_heading_quality(
                    markdown,
                    digest_mode=digest_mode,
                )

        scaffold_fallback_applied = False

        markdown = self._ensure_media_placeholders(
            markdown,
            media_hints=media_hints,
            execution_contract=execution_contract,
        )
        markdown, quality_summary = self._repair_markdown(
            markdown,
            title=title,
            objective=objective,
            required_elements=required_elements,
            digest_mode=digest_mode,
            dense_context=dense_context,
            execution_contract=execution_contract,
        )
        markdown = self._sanitize_student_facing_markdown(
            markdown,
            title=title,
            digest_mode=digest_mode,
            focus_items=required_elements,
        )
        return TracedExecutionResult(
            content=markdown,
            metadata={
                "title": title,
                "coverage_score": float(quality_summary.get("coverage_score", 0.0) or 0.0),
                "quality_score": float(quality_summary.get("quality_score", 0.0) or 0.0),
                "repair_applied": bool(quality_summary.get("repair_applied", False)),
                "repair_actions": list(quality_summary.get("repair_actions", []) or []),
                "quality_summary": quality_summary,
                "heading_repair_applied": heading_repair_applied,
                "scaffold_fallback_applied": scaffold_fallback_applied,
                "heading_missing_module_count": len(list(heading_quality.get("missing_modules") or [])),
            },
        )

    async def _safe_stream_update(
        self,
        callback: Callable[[str], Awaitable[None]],
        markdown: str,
    ) -> None:
        try:
            await callback(markdown)
        except Exception as exc:
            self.logger.warning(
                "docgen_writer_stream_preview_update_failed",
                chapter_index=self.context.chapter_index,
                error=str(exc),
            )

    async def _repair_heading_structure(
        self,
        *,
        title: str,
        objective: str,
        digest_mode: str,
        required_elements: list[str],
        writing_instructions: str,
        source_count: int,
        markdown: str,
        dense_context: str,
        chapter_index: int | None,
        chapter_count: int | None,
    ) -> str | None:
        llm = self.context.resolve_llm_caller()
        messages = build_docgen_heading_repair_messages(
            title=title,
            objective=objective,
            digest_mode=digest_mode,
            required_elements=required_elements,
            writing_instructions=writing_instructions,
            source_count=source_count,
            markdown=markdown,
            dense_context=dense_context,
            chapter_index=chapter_index,
            chapter_count=chapter_count,
        )
        try:
            async def _run_heading_repair(_: object) -> str:
                return str(
                    await llm(
                        messages,
                        **docgen_completion_kwargs_with_metadata(
                            DocGenModelStep.HEADING_REPAIR,
                            digest_mode=digest_mode,
                            extra_metadata=self.context.trace_metadata(
                                chapter_index=chapter_index,
                                substep="heading_repair",
                            ),
                        ),
                    )
                    or ""
                )

            (repaired,) = await run_llm_tasks([None], _run_heading_repair, max_concurrent=1)
        except Exception:
            return None

        cleaned = str(repaired).strip()
        if not cleaned:
            return None
        return cleaned

    def _ensure_media_placeholders(
        self,
        markdown: str,
        *,
        media_hints: Mapping[str, Any],
        execution_contract: Mapping[str, Any],
    ) -> str:
        additions: list[str] = []
        mermaid_hints = [str(item) for item in media_hints.get("mermaid", []) if str(item).strip()]
        quotas = dict(execution_contract.get("media_quota") or {})
        if (
            int(quotas.get("mermaid", 0) or 0) > 0
            and mermaid_hints
            and "```mermaid" not in markdown
            and not has_asset_request(markdown, kind="mermaid")
        ):
            additions.append(build_asset_request_block("mermaid", mermaid_hints[0]))
        if not additions:
            return markdown
        return markdown.rstrip() + "\n\n" + "\n\n".join(additions) + "\n"

    def _repair_markdown(
        self,
        markdown: str,
        *,
        title: str,
        objective: str,
        required_elements: list[str],
        digest_mode: str,
        dense_context: str,
        execution_contract: Mapping[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        repair_actions: list[str] = []
        repaired = markdown.rstrip() + "\n"
        coverage_requirements = [
            str(item).strip()
            for item in list(execution_contract.get("coverage_requirements") or required_elements)
            if str(item).strip()
        ]
        min_word_count = int(execution_contract.get("min_word_count", 0) or 0)
        coverage_score, missing_requirements = self._measure_coverage(
            repaired,
            coverage_requirements=coverage_requirements,
        )
        if missing_requirements:
            repair_actions.append("coverage_unresolved")

        if min_word_count > 0 and count_words(repaired) < min_word_count:
            repair_actions.append("length_unresolved")

        before_presentation_issues = find_docgen_presentation_issues(repaired)
        if before_presentation_issues:
            normalized = normalize_docgen_presentation(
                repaired,
                digest_mode=digest_mode,
                title=title,
                focus_items=required_elements,
            )
            after_presentation_issues = find_docgen_presentation_issues(normalized)
            if normalized and len(after_presentation_issues) < len(before_presentation_issues):
                repaired = normalized
                repair_actions.append("presentation")
                before_presentation_issues = after_presentation_issues

        coverage_score, missing_requirements = self._measure_coverage(
            repaired,
            coverage_requirements=coverage_requirements,
        )
        quality_score = self._estimate_quality_score(
            markdown=repaired,
            coverage_score=coverage_score,
            min_word_count=min_word_count,
        )
        return repaired.rstrip() + "\n", {
            "repair_applied": bool(repair_actions),
            "repair_actions": repair_actions,
            "coverage_score": coverage_score,
            "quality_score": quality_score,
            "missing_requirements": missing_requirements,
            "final_word_count": count_words(repaired),
            "target_word_count": int(execution_contract.get("target_word_count", 0) or 0),
            "min_word_count": min_word_count,
            "presentation": summarize_docgen_presentation(repaired),
            "presentation_issues": before_presentation_issues[:12],
        }

    def _sanitize_student_facing_markdown(
        self,
        markdown: str,
        *,
        title: str,
        digest_mode: str,
        focus_items: list[str],
    ) -> str:
        cleaned = str(markdown or "").replace("\r\n", "\n").replace("\r", "\n")
        cleaned = re.sub(r"```markdown\s*.*?```", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
        cleaned = re.sub(rf"(?im)^\s*课程：\s*(?:course|subj)_[\w-]+\s*$", "", cleaned)
        cleaned = cleaned.replace("```markdown", "")

        forbidden_section_patterns = [
            r"(?ms)^##\s*重点补全\s*\n.*?(?=^##\s|\Z)",
            r"(?ms)^##\s*结构补全\s*\n.*?(?=^##\s|\Z)",
            r"(?ms)^##\s*临考补充笔记\s*\n.*?(?=^##\s|\Z)",
            r"(?ms)^##\s*深入理解补充\s*\n.*?(?=^##\s|\Z)",
            r"(?ms)^###\s*仍需重点覆盖\s*\n.*?(?=^##\s|^###\s|\Z)",
            r"(?ms)^###\s*研究材料.*?\n.*?(?=^##\s|^###\s|\Z)",
        ]
        for pattern in forbidden_section_patterns:
            cleaned = re.sub(pattern, "", cleaned)

        forbidden_line_fragments = (
            "研究笔记",
            "研究材料重组",
            "重点补全",
            "结构补全",
        )
        lines: list[str] = []
        previous = ""
        for raw_line in cleaned.split("\n"):
            line = raw_line.rstrip()
            if any(fragment in line for fragment in forbidden_line_fragments):
                continue
            if line.strip() == previous.strip() and line.strip():
                continue
            lines.append(line)
            previous = line

        cleaned = "\n".join(lines)
        cleaned = normalize_docgen_presentation(
            cleaned,
            digest_mode=digest_mode,
            title=title,
            focus_items=focus_items,
        )
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        if not cleaned.startswith("#"):
            cleaned = f"# {title}\n\n{cleaned}".strip()
        return cleaned + "\n"

    def _measure_coverage(self, markdown: str, *, coverage_requirements: list[str]) -> tuple[float, list[str]]:
        if not coverage_requirements:
            return 1.0, []
        normalized_markdown = self._normalize_blob(markdown)
        missing_requirements: list[str] = []
        hits = 0
        for requirement in coverage_requirements:
            if self._is_requirement_covered(normalized_markdown, requirement):
                hits += 1
                continue
            missing_requirements.append(requirement)
        return round(hits / max(1, len(coverage_requirements)), 4), missing_requirements

    def _is_requirement_covered(self, normalized_markdown: str, requirement: str) -> bool:
        needle = self._normalize_blob(requirement)
        return bool(needle and needle in normalized_markdown)

    def _estimate_quality_score(self, *, markdown: str, coverage_score: float, min_word_count: int) -> float:
        word_count = count_words(markdown)
        length_score = 1.0 if min_word_count <= 0 else min(1.0, word_count / max(1, min_word_count))
        heading_score = 1.0 if markdown.count("\n## ") >= 3 else 0.75
        placeholder_bonus = 0.1 if any(token in markdown for token in _PLACEHOLDER_TOKEN_MAP.values()) else 0.0
        score = (coverage_score * 0.55) + (length_score * 0.3) + (heading_score * 0.15) + placeholder_bonus
        return round(min(1.0, score), 4)

    def _normalize_blob(self, value: str) -> str:
        return re.sub(r"\s+", "", str(value or "").strip()).casefold()


__all__ = ["DocGenWriterRuntime"]
