"""Workflow-local writer runtime for digest DocGen."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.shared.infra.traced_execution import BaseTracedExecution, TracedExecutionResult
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.skills import collect_recommended_tool_tags, render_prompt_scoped_skillpacks
from app.teaching.documents import ensure_chapter_learning_scaffold, resolve_effective_chapter_title
from app.workflows.digest.prompts import build_docgen_writer_messages


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
            skillpack_guidance=skillpack_guidance,
            recommended_tool_tags=recommended_tool_tags,
        )
        try:
            markdown = await llm(
                messages,
                task_type=TaskType.DOCGEN,
                tier="advanced" if digest_mode == "systematic" else "smart",
                extra_metadata=self.context.trace_metadata(chapter_index=self.context.chapter_index),
            )
        except Exception:
            markdown = self._fallback_markdown(title=title, objective=objective, dense_context=dense_context)

        markdown = str(markdown).strip()
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
        if media_hints:
            markdown = self._ensure_media_placeholders(markdown, media_hints)
        return TracedExecutionResult(
            content=markdown,
            metadata={
                "title": title,
                "selected_skillpacks": list(selected_skillpacks or []),
                "recommended_tool_tags": recommended_tool_tags,
            },
        )

    def _fallback_markdown(self, *, title: str, objective: str, dense_context: str) -> str:
        body = dense_context.strip()[:5000] or "当前没有足够的外部研究素材，本章基于已确认的构建方案与现有知识进行整理。"
        summary_line = f"学习目标：{objective}" if objective else "学习目标：先理解本章最核心的知识主线。"
        return (
            f"# {title}\n\n"
            f"> [!TIP]\n> {summary_line}\n\n"
            "## 核心内容\n\n"
            f"{body}\n\n"
            "## 快速回顾\n\n"
            "- 试着用一句话复述本章最重要的概念。\n"
            "- 把这个概念和一个具体例子或应用场景对应起来。\n"
        )

    def _ensure_media_placeholders(self, markdown: str, media_hints: Mapping[str, Any]) -> str:
        additions: list[str] = []
        mermaid_hints = [str(item) for item in media_hints.get("mermaid", []) if str(item).strip()]
        image_hints = [str(item) for item in media_hints.get("images", []) if str(item).strip()]
        if mermaid_hints and "[MERMAID:" not in markdown:
            additions.append(f"<!-- [MERMAID: {mermaid_hints[0]}] -->")
        if image_hints and "[IMAGE:" not in markdown:
            additions.append(f"<!-- [IMAGE: {image_hints[0]}] -->")
        if not additions:
            return markdown
        return markdown.rstrip() + "\n\n" + "\n\n".join(additions) + "\n"


__all__ = ["DocGenWriterRuntime"]
