"""Workflow-local writer runtime for digest DocGen."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.shared.infra.execution import BaseTracedExecution, TracedExecutionResult
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.skills import collect_recommended_tool_tags, render_prompt_scoped_skillpacks
from app.shared.infra.tools.builtin.markdown_processing import count_words
from app.teaching.documents import (
    analyze_chapter_heading_quality,
    ensure_chapter_learning_scaffold,
    resolve_effective_chapter_title,
)
from app.workflows.digest.prompts import build_docgen_heading_repair_messages, build_docgen_writer_messages

_PLACEHOLDER_TOKEN_MAP = {
    "mermaid": "[MERMAID:",
    "images": "[IMAGE:",
    "interactive_html": "[INTERACTIVE:",
}


class DocGenWriterRuntime(BaseTracedExecution):
    @property
    def trace_namespace(self) -> str:
        return "workflow_runtime.docgen"

    @property
    def trace_name(self) -> str:
        return "writer"

    async def execute(
        self,
        *,
        chapter_plan: Mapping[str, Any],
        dense_context: str,
        tone: str,
        digest_mode: str,
        selected_skillpacks: list[str] | None = None,
        user_goal: str = "",
    ) -> TracedExecutionResult:
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
        skillpack_guidance = render_prompt_scoped_skillpacks(
            selected_skillpacks,
            prompt_scope="digest.docgen.writer",
            bindings={
                "subject": self.context.subject,
                "user_goal": user_goal,
                "chapter_title": title,
                "topic": title,
                "concept": title,
            },
        )
        recommended_tool_tags = collect_recommended_tool_tags(
            selected_skillpacks,
            prompt_scope="digest.docgen.writer",
        )
        messages = build_docgen_writer_messages(
            title=title,
            objective=objective,
            tone=tone,
            digest_mode=digest_mode,
            required_elements=required_elements,
            writing_instructions=writing_instructions,
            source_count=source_count,
            dense_context=dense_context,
            chapter_index=chapter_index,
            chapter_count=chapter_count,
            execution_contract=execution_contract,
            skillpack_guidance=skillpack_guidance,
            recommended_tool_tags=recommended_tool_tags,
        )
        markdown = await llm(
            messages,
            task_type=TaskType.DOCGEN,
            tier="reason" if digest_mode == "systematic" else "primary",
            extra_metadata=self.context.trace_metadata(chapter_index=self.context.chapter_index),
        )

        markdown = str(markdown).strip()
        heading_quality = analyze_chapter_heading_quality(
            markdown,
            digest_mode=digest_mode,
        )
        heading_repair_applied = False
        if bool(heading_quality.get("needs_agent_repair")):
            repaired_markdown = await self._repair_heading_structure(
                title=title,
                objective=objective,
                tone=tone,
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
                "selected_skillpacks": list(selected_skillpacks or []),
                "recommended_tool_tags": recommended_tool_tags,
            },
        )

    def _fallback_markdown(self, *, title: str, objective: str, dense_context: str, digest_mode: str) -> str:
        body = dense_context.strip()[:5000] or "当前没有足够的外部研究素材，本章基于已确认的构建方案与现有知识进行整理。"
        summary_line = f"学习目标：{objective}" if objective else "学习目标：先把本章最核心的概念、方法和应用场景讲清楚。"
        normalized_mode = str(digest_mode or "").strip().lower()
        if normalized_mode == "sprint":
            return (
                f"# {title}\n\n"
                f"> [!TIP]\n> {summary_line}\n\n"
                "## 这一章到底在考什么\n\n"
                "- 先判断本章解决的核心问题是什么，再去记结论和题型。\n"
                "- 做题时优先识别概念、条件和常见问法，不要只盯公式表面。\n\n"
                "## 先把核心概念讲清楚\n\n"
                f"{body}\n\n"
                "## 典型题怎么想怎么做\n\n"
                "1. 先识别题目在考哪一个概念、性质或方法。\n"
                "2. 再判断解题需要满足哪些前提条件。\n"
                "3. 最后回到步骤、结论和失分点，形成稳定套路。\n\n"
                "## 最容易混淆和失分的地方\n\n"
                "- 不要只背结论，要同时记住适用条件和不能硬套的场景。\n"
                "- 若题目换了问法，要回到本质而不是照抄模板步骤。\n\n"
                "## 本章最后压缩回看\n\n"
                "- 用一句话讲清本章最关键的判断依据。\n"
                "- 说出一个最常见题型和一个最容易错的点。\n"
            )
        return (
            f"# {title}\n\n"
            f"> [!IMPORTANT]\n> {summary_line}\n\n"
            "## 这一章要解决什么问题\n\n"
            "- 先明确本章讨论对象、问题背景和学习目标。\n\n"
            "## 核心定义与结构先讲清楚\n\n"
            f"{body}\n\n"
            "## 关键推理是怎样成立的\n\n"
            "- 先交代前提，再说明结论，最后解释推理链条如何展开。\n\n"
            "## 例子或应用如何落地\n\n"
            "- 用一个典型例子把抽象结构落到具体场景里。\n\n"
            "## 本章最后要带走什么\n\n"
            "- 总结本章最核心的定义、关系和使用边界。\n"
            "- 说明它与上一章、下一章之间怎么衔接。\n"
        )

    async def _repair_heading_structure(
        self,
        *,
        title: str,
        objective: str,
        tone: str,
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
            tone=tone,
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
                tier="fast",
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
        image_hints = [str(item) for item in media_hints.get("images", []) if str(item).strip()]
        interactive_hints = [str(item) for item in media_hints.get("interactive", []) if str(item).strip()]
        quotas = dict(execution_contract.get("media_quota") or {})
        if int(quotas.get("mermaid", 0) or 0) > 0 and "[MERMAID:" not in markdown:
            additions.append(f"<!-- [MERMAID: {(mermaid_hints[:1] or [f'{title} 的关键结构关系图'])[0]}] -->")
        if int(quotas.get("images", 0) or 0) > 0 and "[IMAGE:" not in markdown:
            additions.append(f"<!-- [IMAGE: {(image_hints[:1] or [f'{title} 的讲义配图建议'])[0]}] -->")
        if int(quotas.get("interactive_html", 0) or 0) > 0 and "[INTERACTIVE:" not in markdown:
            default_interactive_hint = (
                f"{title} 的公式推导展开器"
                if "公式" in "".join(interactive_hints) or "推导" in "".join(interactive_hints) or digest_mode == "systematic"
                else f"{title} 的概念对比自检块"
            )
            additions.append(f"<!-- [INTERACTIVE: {(interactive_hints[:1] or [default_interactive_hint])[0]}] -->")
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
        heading_score = 1.0 if markdown.count("\n## ") >= 5 else 0.75
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
