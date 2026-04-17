"""Whole-document review for rewritten DocGen."""

from __future__ import annotations

from collections import Counter

from app.shared.infra.tools.builtin.markdown_processing import count_words
from app.workflows.digest.docgen.lib.models import EnhancedChapterDraft, MergeReviewIssue, MergeReviewReport


def build_merge_review_report(
    *,
    enhanced_chapters: list[EnhancedChapterDraft],
    expected_chapter_count: int,
    plan_summary: str,
) -> MergeReviewReport:
    del plan_summary
    issues: list[MergeReviewIssue] = []
    if len(enhanced_chapters) != expected_chapter_count:
        issues.append(
            MergeReviewIssue(
                severity="warning",
                issue_type="chapter_count",
                detail=f"增强章节数 {len(enhanced_chapters)} 与计划章节数 {expected_chapter_count} 不一致。",
                suggestion="检查失败章节并决定是否重新生成。",
            )
        )
    title_counts = Counter(chapter.title.strip() for chapter in enhanced_chapters if chapter.title.strip())
    for title, count in title_counts.items():
        if count > 1:
            issues.append(
                MergeReviewIssue(
                    severity="warning",
                    issue_type="duplicate_title",
                    detail=f"章节标题重复：{title}",
                    suggestion="后续可在章节增强中细化标题。",
                )
            )
    low_quality = [
        chapter
        for chapter in enhanced_chapters
        if chapter.quality_signals.quality_score and chapter.quality_signals.quality_score < 0.55
    ]
    for chapter in low_quality[:5]:
        issues.append(
            MergeReviewIssue(
                severity="warning",
                chapter_index=chapter.chapter_index,
                issue_type="quality",
                detail=f"章节质量分偏低：{chapter.quality_signals.quality_score}",
                suggestion="可重新生成或人工复核该章。",
            )
        )
    no_sources = [chapter for chapter in enhanced_chapters if not chapter.source_details]
    for chapter in no_sources[:5]:
        issues.append(
            MergeReviewIssue(
                severity="warning",
                chapter_index=chapter.chapter_index,
                issue_type="source",
                detail="章节缺少可追踪来源。",
                suggestion="建议补充本地资料或允许外部检索。",
            )
        )
    total_words = sum(count_words(chapter.markdown) for chapter in enhanced_chapters)
    decision = "publish" if not issues else "publish_with_warnings"
    return MergeReviewReport(
        passed=not any(issue.severity == "error" for issue in issues),
        decision=decision,
        issues=issues,
        coverage_summary={
            "chapter_count": len(enhanced_chapters),
            "expected_chapter_count": expected_chapter_count,
            "total_words": total_words,
        },
        style_summary={
            "duplicate_title_count": sum(1 for _title, count in title_counts.items() if count > 1),
            "low_quality_chapter_count": len(low_quality),
        },
        source_summary={
            "chapters_without_sources": [chapter.chapter_index for chapter in no_sources],
            "chapter_source_count": {
                str(chapter.chapter_index): len(chapter.source_details)
                for chapter in enhanced_chapters
            },
        },
    )


__all__ = ["build_merge_review_report"]
