"""DocGen 执行策略。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from app.shared.infra.config import get_settings
from app.workflows.digest.docs.services.cleanse_service import analyze_cleanliness
from app.workflows.digest.docs.services.writer_service import analyze_chapter_structure


@dataclass(slots=True)
class CleanseDecision:
    """单个文本块的清洗决策。"""

    use_llm: bool
    reason: str


@dataclass(slots=True)
class OutlineExecutionPlan:
    """Planner output for outline scheduling."""

    mode: str
    reason: str


@dataclass(slots=True)
class ReviewExecutionPlan:
    """Planner output for review scheduling."""

    mode: str
    reason: str


@dataclass(slots=True)
class DocGenExecutionStrategy:
    """DocGen 平衡加速执行策略。"""

    max_parallel_chapters: int
    io_parallelism: int
    outline_fast_path_max_chunks: int
    skip_llm_cleanse_for_clean_markdown: bool
    skip_llm_review_for_single_chapter: bool
    review_fast_path_max_chapters: int
    review_retry_mode: str
    metadata_fallback_llm: bool
    chapter_semaphore: asyncio.Semaphore = field(init=False)
    io_semaphore: asyncio.Semaphore = field(init=False)

    def __post_init__(self) -> None:
        self.chapter_semaphore = asyncio.Semaphore(max(1, self.max_parallel_chapters))
        self.io_semaphore = asyncio.Semaphore(max(1, self.io_parallelism))

    @classmethod
    def from_settings(cls) -> "DocGenExecutionStrategy":
        settings = get_settings()
        return cls(
            max_parallel_chapters=settings.docgen_max_parallel_chapters,
            io_parallelism=settings.docgen_io_parallelism,
            outline_fast_path_max_chunks=settings.docgen_outline_fast_path_max_chunks,
            skip_llm_cleanse_for_clean_markdown=settings.docgen_skip_llm_cleanse_for_clean_markdown,
            skip_llm_review_for_single_chapter=settings.docgen_skip_llm_review_for_single_chapter,
            review_fast_path_max_chapters=settings.docgen_review_fast_path_max_chapters,
            review_retry_mode=settings.docgen_review_retry_mode,
            metadata_fallback_llm=settings.docgen_metadata_fallback_llm,
        )

    def decide_cleanse(self, *, source_filename: str, content: str) -> CleanseDecision:
        """判断当前文本块是否需要 LLM 自愈。"""

        analysis = analyze_cleanliness(source_filename=source_filename, content=content)
        if analysis["force_llm"]:
            return CleanseDecision(use_llm=True, reason=analysis["reason"])
        if self.skip_llm_cleanse_for_clean_markdown and analysis["clean_markdown"]:
            return CleanseDecision(use_llm=False, reason=analysis["reason"])
        return CleanseDecision(use_llm=True, reason=analysis["reason"])


    def plan_outline(
        self,
        *,
        chunk_count: int,
        local_outlines: list[dict],
        user_prompt: str | None,
    ) -> OutlineExecutionPlan:
        if chunk_count <= 0:
            return OutlineExecutionPlan(mode="fallback", reason="empty_chunks")

        return OutlineExecutionPlan(
            mode="global_llm",
            reason="docs_require_explicit_chapter_planning",
        )

    def plan_review(
        self,
        *,
        total_chapters: int,
        source_chunk_count: int,
        markdown: str,
        user_prompt: str | None,
    ) -> ReviewExecutionPlan:
        structure = analyze_chapter_structure(markdown)
        prompt_present = bool(user_prompt and user_prompt.strip())
        if (
            all(structure.values())
            and len(markdown) >= 900
            and source_chunk_count <= 3
            and not prompt_present
        ):
            return ReviewExecutionPlan(
                mode="rule_based_only",
                reason="structure_complete_and_content_sufficient",
            )

        if (
            self.skip_llm_review_for_single_chapter
            and total_chapters <= self.review_fast_path_max_chapters
            and source_chunk_count <= 1
            and all(structure.values())
            and not prompt_present
        ):
            return ReviewExecutionPlan(
                mode="rule_based_only",
                reason="single_chapter_structure_complete",
            )

        return ReviewExecutionPlan(
            mode="llm_review",
            reason="needs_semantic_review",
        )


__all__ = [
    "CleanseDecision",
    "DocGenExecutionStrategy",
    "OutlineExecutionPlan",
    "ReviewExecutionPlan",
]
