"""Workflow-local writer runtime for digest DocGen."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from app.shared.infra.execution import BaseTracedExecution, TracedExecutionResult
from app.shared.infra.llm_support import acompletion_stream
from app.shared.infra.tools.builtin.markdown_processing import count_words, normalize_markdown_rendering
from app.workflows.digest.common.pedagogy import (
    analyze_chapter_heading_quality,
    ensure_chapter_learning_scaffold,
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
from app.workflows.digest.docgen.lib.textbook_style import (
    build_textbook_heading,
    choose_heading_focus,
    normalize_textbook_headings,
)
from app.workflows.digest.docgen.mode_profiles import get_docgen_mode_profile

_PLACEHOLDER_TOKEN_MAP = {
    "asset_request": ASSET_REQUEST_LANGUAGE,
}


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
            chunks: list[str] = []
            try:
                async for chunk in acompletion_stream(
                    messages,
                    **writer_model_kwargs,
                ):
                    chunks.append(str(chunk))
                    await self._safe_stream_update(on_stream_update, "".join(chunks))
                markdown = "".join(chunks)
                await self._safe_stream_update(on_stream_update, markdown)
            except Exception as exc:
                self.logger.warning(
                    "docgen_writer_stream_failed_falling_back",
                    chapter_index=chapter_index,
                    streamed_chars=sum(len(item) for item in chunks),
                    error=str(exc),
                )

        if not markdown.strip():
            markdown = await llm(
                messages,
                **writer_model_kwargs,
            )

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
        if bool(heading_quality.get("needs_scaffold_fallback")):
            markdown = ensure_chapter_learning_scaffold(
                markdown,
                title=title,
                objective=objective,
                required_elements=required_elements,
                digest_mode=digest_mode,
                source_count=source_count,
                chapter_index=chapter_index,
                chapter_count=chapter_count,
            )
            scaffold_fallback_applied = True
            heading_quality = analyze_chapter_heading_quality(
                markdown,
                digest_mode=digest_mode,
            )

        markdown = self._ensure_media_placeholders(
            markdown,
            media_hints=media_hints,
            execution_contract=execution_contract,
            digest_mode=digest_mode,
            title=title,
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
            repaired = await llm(
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
        digest_mode: str,
        title: str,
    ) -> str:
        additions: list[str] = []
        mermaid_hints = [str(item) for item in media_hints.get("mermaid", []) if str(item).strip()]
        quotas = dict(execution_contract.get("media_quota") or {})
        if int(quotas.get("mermaid", 0) or 0) > 0 and "```mermaid" not in markdown and not has_asset_request(markdown, kind="mermaid"):
            additions.append(build_asset_request_block("mermaid", (mermaid_hints[:1] or [f"{title} 的关键结构关系图"])[0]))
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
            repaired = repaired.rstrip() + "\n\n" + self._build_repair_section(
                title=title,
                objective=objective,
                digest_mode=digest_mode,
                missing_requirements=missing_requirements,
                dense_context=dense_context,
            )
            repair_actions.append("coverage")

        if min_word_count > 0 and count_words(repaired) < min_word_count:
            repaired = repaired.rstrip() + "\n\n" + self._build_expansion_section(
                title=title,
                digest_mode=digest_mode,
                required_elements=required_elements,
                dense_context=dense_context,
            )
            repair_actions.append("length")

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
        }

    def _build_repair_section(
        self,
        *,
        title: str,
        objective: str,
        digest_mode: str,
        missing_requirements: list[str],
        dense_context: str,
    ) -> str:
        mode_profile = get_docgen_mode_profile(digest_mode)
        focus = choose_heading_focus(missing_requirements, fallback=title)
        heading = build_textbook_heading(
            "coverage",
            digest_mode=digest_mode,
            focus=focus,
            fallback_title=title,
        )
        lines = [
            heading,
            "",
            f"这一节补齐《{title}》中还需要讲清的知识点，重点放在定义、判断依据和典型问法上。",
        ]
        if objective.strip():
            lines.append(f"本章目标：{objective.strip()}")
        lines.extend(["", build_textbook_heading("points", digest_mode=digest_mode, level=3), ""])
        lines.extend(f"- {item}：说明它的定义、适用条件和在题目中的常见问法。" for item in missing_requirements[:5])
        if mode_profile.is_sprint:
            lines.extend(
                [
                    "",
                    build_textbook_heading("questions", digest_mode=digest_mode, level=3),
                    "",
                    "- 题目中的哪个条件决定了可以使用这一结论？",
                    "- 这一类题最短的判断路径是什么？",
                    "- 换一种问法时，哪些步骤仍然不变？",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    build_textbook_heading("questions", digest_mode=digest_mode, level=3),
                    "",
                    "- 这一部分的前提、结论和结构关系分别是什么？",
                    "- 哪一步推理最容易跳步，必须补解释？",
                    "- 哪个例子最能帮助把抽象结论落到具体情境？",
                ]
            )
        return "\n".join(lines).strip()

    def _build_expansion_section(
        self,
        *,
        title: str,
        digest_mode: str,
        required_elements: list[str],
        dense_context: str,
    ) -> str:
        mode_profile = get_docgen_mode_profile(digest_mode)
        focus_items = required_elements[:4] or (
            ["核心概念", "关键方法", "典型例子"] if mode_profile.is_sprint else ["定义", "推理", "应用"]
        )
        focus = choose_heading_focus(focus_items, fallback=title)
        heading = build_textbook_heading(
            "summary",
            digest_mode=digest_mode,
            focus=focus,
            fallback_title=title,
        )
        lines = [
            heading,
            "",
            f"下面把《{title}》里最重要的知识压缩成适合整理笔记的结构。",
            "",
            build_textbook_heading("points", digest_mode=digest_mode, level=3),
            "",
        ]
        lines.extend(f"- {item}" for item in focus_items)
        if mode_profile.is_sprint:
            lines.extend(
                [
                    "",
                    build_textbook_heading("questions", digest_mode=digest_mode, level=3),
                    "",
                    "- 这一步到底在判断什么条件？",
                    "- 这个结论什么时候能直接用，什么时候不能硬套？",
                    "- 题目换一种表述时，判断路径是否仍然成立？",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    build_textbook_heading("links", digest_mode=digest_mode, level=3),
                    "",
                    "- 先把定义、符号和成立条件串成一条稳定主线。",
                    "- 再把推理过程和应用场景对应起来，避免只记孤立结论。",
                    "- 最后补上边界与反例，避免把结论用到不适用的场景。",
                ]
            )
        return "\n".join(lines).strip()

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
        cleaned = re.sub(rf"(?im)^\s*学科：\s*subj_[\w-]+\s*$", "", cleaned)
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
        cleaned = normalize_textbook_headings(
            cleaned,
            digest_mode=digest_mode,
            fallback_title=title,
            focus_items=focus_items,
        )
        cleaned = normalize_markdown_rendering(cleaned)
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
            needle = self._normalize_blob(requirement)
            if needle and needle in normalized_markdown:
                hits += 1
                continue
            missing_requirements.append(requirement)
        return round(hits / max(1, len(coverage_requirements)), 4), missing_requirements

    def _estimate_quality_score(self, *, markdown: str, coverage_score: float, min_word_count: int) -> float:
        word_count = count_words(markdown)
        length_score = 1.0 if min_word_count <= 0 else min(1.0, word_count / max(1, min_word_count))
        heading_score = 1.0 if markdown.count("\n## ") >= 3 else 0.75
        placeholder_bonus = 0.1 if any(token in markdown for token in _PLACEHOLDER_TOKEN_MAP.values()) else 0.0
        score = (coverage_score * 0.55) + (length_score * 0.3) + (heading_score * 0.15) + placeholder_bonus
        return round(min(1.0, score), 4)

    def _extract_context_points(self, dense_context: str, *, limit: int) -> list[str]:
        fragments = [
            fragment.strip(" -")
            for fragment in re.split(r"[\n。；;]+", str(dense_context or "").strip())
            if fragment.strip()
        ]
        deduped: list[str] = []
        seen: set[str] = set()
        for fragment in fragments:
            normalized = fragment.casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(fragment[:140])
            if len(deduped) >= limit:
                break
        return deduped

    def _normalize_blob(self, value: str) -> str:
        return re.sub(r"\s+", "", str(value or "").strip()).casefold()


__all__ = ["DocGenWriterRuntime"]
