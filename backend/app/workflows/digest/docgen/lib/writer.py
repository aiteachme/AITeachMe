"""Workflow-local writer runtime for digest DocGen."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from time import perf_counter
from typing import Any

from app.shared.infra.env_support import get_env_bounded_float, get_env_bounded_int
from app.shared.infra.execution import BaseTracedExecution, TracedExecutionResult
from app.shared.infra.llm_support import acompletion_stream
from app.shared.infra.tools.builtin.markdown_processing import count_words
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
from app.workflows.digest.docgen.lib.presentation_policy import (
    find_docgen_presentation_issues,
    normalize_docgen_presentation,
    summarize_docgen_presentation,
)
from app.workflows.digest.docgen.lib.textbook_style import (
    build_textbook_heading,
    choose_heading_focus,
)
from app.workflows.digest.docgen.mode_profiles import get_docgen_mode_profile

_PLACEHOLDER_TOKEN_MAP = {
    "asset_request": ASSET_REQUEST_LANGUAGE,
}

_GENERIC_REQUIREMENT_TOKENS = {
    "说明",
    "定义",
    "适用",
    "条件",
    "常见",
    "问法",
    "核心",
    "要点",
    "典型",
    "判断",
    "问题",
    "应用",
    "讲清",
    "分析",
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
            chunks: list[str] = []
            streamed_chars = 0
            stream_callback_last_at = perf_counter()
            stream_callback_last_len = 0
            try:
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
                markdown = "".join(chunks)
                await self._safe_stream_update(on_stream_update, markdown)
            except Exception as exc:
                self.logger.warning(
                    "docgen_writer_stream_failed_falling_back",
                    chapter_index=chapter_index,
                    streamed_chars=streamed_chars,
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
        lines = [
            "## 补充掌握检查",
            "",
            f"围绕《{title}》，可以把注意力集中到几个容易漏掉的连接点上。",
        ]
        if objective.strip():
            lines.append(f"本章目标仍然是：{objective.strip()}")
        lines.extend(["", "复习时优先检查这些点是否已经能用自己的话讲清："])
        for item in missing_requirements[:5]:
            lines.append(
                f"- **{item}**：它和本章主线是什么关系，在哪类题目或场景里会被触发，最容易和哪个相邻概念混淆。"
            )
        if mode_profile.is_sprint:
            lines.extend(
                [
                    "",
                    "做题前不必重新背一遍整章，先抓住题目给出的结构条件，再判断它对应本章哪一种方法。",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "如果后续继续系统学习，可以把这些点放回定义、推理和例子的链条中检查，而不是孤立记忆。",
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
            f"为了让《{title}》这一章更完整，可以把正文再向外补一层复习抓手。",
            "",
        ]
        for item in focus_items:
            lines.append(f"- **{item}**：回到正文里找到它承担的角色，再确认它对应的条件、步骤或例子。")
        if mode_profile.is_sprint:
            lines.extend(
                [
                    "",
                    "突击复习时，把这些抓手压缩成“看条件、选方法、验结论”的三步即可。",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "系统学习时，重点不是把清单背完，而是把概念、推理和应用之间的因果关系串起来。",
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
        if needle and needle in normalized_markdown:
            return True
        tokens = self._requirement_tokens(requirement)
        if not tokens:
            return False
        matched = [token for token in tokens if self._normalize_blob(token) in normalized_markdown]
        if len(matched) >= min(2, len(tokens)):
            return True
        return any(len(self._normalize_blob(token)) >= 4 for token in matched)

    def _estimate_quality_score(self, *, markdown: str, coverage_score: float, min_word_count: int) -> float:
        word_count = count_words(markdown)
        length_score = 1.0 if min_word_count <= 0 else min(1.0, word_count / max(1, min_word_count))
        heading_score = 1.0 if markdown.count("\n## ") >= 3 else 0.75
        placeholder_bonus = 0.1 if any(token in markdown for token in _PLACEHOLDER_TOKEN_MAP.values()) else 0.0
        score = (coverage_score * 0.55) + (length_score * 0.3) + (heading_score * 0.15) + placeholder_bonus
        return round(min(1.0, score), 4)

    def _extract_context_points(self, dense_context: str, *, limit: int) -> list[str]:
        fragments: list[str] = []
        for raw_fragment in re.split(r"[\n。；;]+", str(dense_context or "").strip()):
            fragment = raw_fragment.strip(" -")
            fragment = re.sub(r"^#{1,6}\s*", "", fragment).strip()
            if not fragment or fragment.startswith(("[!", "![", "```")):
                continue
            fragments.append(fragment)
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

    def _requirement_tokens(self, value: str) -> list[str]:
        tokens: list[str] = []
        for raw in re.split(r"[\s,，、;；:：/／|｜()（）《》“”\"'`]+|作为|以及|并且|和|与|及|的", str(value or "")):
            token = raw.strip()
            if len(token) < 2 or token in _GENERIC_REQUIREMENT_TOKENS:
                continue
            if token.endswith("的") and len(token) > 2:
                token = token[:-1]
            if token and token not in _GENERIC_REQUIREMENT_TOKENS:
                tokens.append(token)
        return list(dict.fromkeys(tokens))


__all__ = ["DocGenWriterRuntime"]
