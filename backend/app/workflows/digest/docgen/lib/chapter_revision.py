"""Bounded chapter quality critique and rewrite for DocGen."""

from __future__ import annotations

from collections.abc import Sequence

import structlog

from app.shared.infra.tools.builtin.markdown_processing import count_words
from app.workflows.digest.docgen.lib.chapter_planning import estimate_quality_from_markdown
from app.workflows.digest.docgen.lib.model_policy import DocGenModelStep, docgen_completion_kwargs_with_metadata
from app.workflows.digest.docgen.lib.models import ChapterQualitySignals
from app.workflows.digest.docgen.prompts.chapter_rewrite import build_chapter_rewrite_messages

logger = structlog.get_logger(__name__)


def critique_chapter(
    *,
    markdown: str,
    required_points: Sequence[str],
    digest_mode: str,
    source_count: int,
    min_word_count: int,
) -> ChapterQualitySignals:
    warnings: list[str] = []
    if count_words(markdown) < min_word_count:
        warnings.append("章节长度低于最低目标。")
    if markdown.count("\n## ") < (2 if str(digest_mode).strip().lower() == "sprint" else 3):
        warnings.append("章节结构不够完整。")
    coverage_score = 0.0
    if source_count <= 0:
        warnings.append("缺少可追踪来源。")
    quality_score = estimate_quality_from_markdown(
        markdown,
        required_points=required_points,
        min_word_count=min_word_count,
    )
    return ChapterQualitySignals(
        coverage_score=coverage_score,
        quality_score=quality_score,
        warnings=warnings,
        critic_summary="；".join(warnings) if warnings else "章节质量检查通过。",
    )


async def maybe_rewrite_chapter(
    *,
    llm,
    markdown: str,
    title: str,
    digest_mode: str,
    required_points: list[str],
    dense_context: str,
    quality: ChapterQualitySignals,
    min_word_count: int,
    max_retries: int,
    extra_metadata: dict,
) -> tuple[str, ChapterQualitySignals]:
    if max_retries <= 0 or quality.quality_score >= 0.62 or not quality.warnings:
        return markdown, quality
    try:
        rewritten = await llm(
            build_chapter_rewrite_messages(
                title=title,
                digest_mode=digest_mode,
                required_points=required_points,
                warnings=quality.warnings,
                markdown=markdown,
                dense_context=dense_context,
            ),
            **docgen_completion_kwargs_with_metadata(
                DocGenModelStep.CHAPTER_REWRITE,
                digest_mode=digest_mode,
                extra_metadata=extra_metadata,
                substep="chapter_rewrite",
            ),
        )
    except Exception as exc:
        logger.warning("docgen_chapter_rewrite_failed", title=title, error=str(exc))
        return markdown, quality
    rewritten_text = str(rewritten or "").strip()
    if not rewritten_text:
        return markdown, quality
    repaired_quality = critique_chapter(
        markdown=rewritten_text,
        required_points=required_points,
        digest_mode=digest_mode,
        source_count=1,
        min_word_count=max(1, int(min_word_count or count_words(markdown) * 0.7)),
    )
    repaired_quality.rewrite_used = True
    return rewritten_text + "\n", repaired_quality


__all__ = ["critique_chapter", "maybe_rewrite_chapter"]
