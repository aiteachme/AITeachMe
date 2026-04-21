"""Workflow-local writer runtime for digest DocGen."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.shared.infra.execution import BaseTracedExecution, TracedExecutionResult
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.tools.builtin.markdown_processing import count_words, normalize_markdown_rendering
from app.workflows.digest.common.pedagogy import (
    analyze_chapter_heading_quality,
    ensure_chapter_learning_scaffold,
    resolve_effective_chapter_title,
)
from app.workflows.digest.docgen.prompts import (
    build_docgen_heading_repair_messages,
    build_docgen_writer_messages,
)
from app.workflows.digest.docgen.lib.asset_requests import (
    ASSET_REQUEST_LANGUAGE,
    build_asset_request_block,
    has_asset_request,
    strip_asset_requests,
)

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
        markdown = await llm(
            messages,
            task_type=TaskType.DOCGEN,
            model="reason" if digest_mode == "systematic" else "primary",
            extra_metadata=self.context.trace_metadata(chapter_index=self.context.chapter_index),
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
        markdown = self._sanitize_student_facing_markdown(markdown, title=title)
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
                task_type=TaskType.DOCGEN_LIGHT,
                model="light",
                extra_metadata=self.context.trace_metadata(
                    chapter_index=chapter_index,
                    substep="heading_repair",
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
        heading = "## 再把关键点压实一遍" if str(digest_mode or "").strip().lower() == "sprint" else "## 再把关键结构补稳"
        lines = [
            heading,
            "",
            f"如果只看一遍还不够稳，下面这些内容需要回到《{title}》里再压一遍。",
        ]
        if objective.strip():
            lines.append(f"本章目标：{objective.strip()}")
        lines.extend(["", "### 这几项不能漏", ""])
        lines.extend(f"- {item}：回看定义、判断依据和题目中最常见的问法。" for item in missing_requirements[:5])
        if str(digest_mode or "").strip().lower() == "sprint":
            lines.extend(
                [
                    "",
                    "### 回看时优先问自己",
                    "",
                    "- 这一点到底在考哪个概念、条件或结论？",
                    "- 我能不能说清它为什么成立，而不是只记结果？",
                    "- 如果题目换个问法，我还能不能用同一套判断路径？",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "### 回看时优先问自己",
                    "",
                    "- 这一部分的前提、结论和结构关系分别是什么？",
                    "- 哪一步推理最容易跳步，必须补解释？",
                    "- 哪个例子最能帮助我把抽象结论落到具体情境？",
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
        normalized_mode = str(digest_mode or "").strip().lower()
        heading = "## 本章压缩复盘" if normalized_mode == "sprint" else "## 本章补充理解"
        focus_items = required_elements[:4] or (["核心概念", "关键方法", "典型例子"] if normalized_mode == "sprint" else ["定义", "推理", "应用"])
        lines = [
            heading,
            "",
            f"下面把《{title}》里最该继续记牢的内容压缩成一组复盘抓手。",
            "",
            "### 优先回看这些内容",
            "",
        ]
        lines.extend(f"- {item}" for item in focus_items)
        if normalized_mode == "sprint":
            lines.extend(
                [
                    "",
                    "### 做题时要主动问自己",
                    "",
                    "- 这一步到底在判断什么条件？",
                    "- 这个结论什么时候能直接用，什么时候不能硬套？",
                    "- 如果题目换一个问法，我还能不能把同一套路迁过去？",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "### 继续往下学时要串起来的关系",
                    "",
                    "- 先把定义、符号和成立条件串成一条稳定主线。",
                    "- 再把推理过程和应用场景对应起来，避免只记孤立结论。",
                    "- 最后回看边界与反例，确认自己不是“看懂了但其实没真懂”。",
                ]
            )
        return "\n".join(lines).strip()

    def _sanitize_student_facing_markdown(self, markdown: str, *, title: str) -> str:
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
            r"(?ms)^###\s*可直接回看这些研究线索\s*\n.*?(?=^##\s|^###\s|\Z)",
            r"(?ms)^###\s*研究材料重组\s*\n.*?(?=^##\s|^###\s|\Z)",
        ]
        for pattern in forbidden_section_patterns:
            cleaned = re.sub(pattern, "", cleaned)

        forbidden_line_fragments = (
            "研究笔记",
            "可直接回看这些研究线索",
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
