"""Whole-document consistency review for DocGen."""

from __future__ import annotations

from collections import Counter

from app.workflows.digest.docgen.lib.models import (
    DocumentBackbone,
    DocumentConsistencyReport,
    ReviewedChapterDraft,
)


def review_document_consistency(
    *,
    reviewed_chapters: list[ReviewedChapterDraft],
    document_backbone: DocumentBackbone,
    expected_chapter_count: int,
) -> DocumentConsistencyReport:
    issues: list[dict[str, object]] = []
    if expected_chapter_count and len(reviewed_chapters) != expected_chapter_count:
        issues.append(
            {
                "severity": "warning",
                "issue_type": "chapter_count",
                "detail": f"预期 {expected_chapter_count} 章，实际可发布 {len(reviewed_chapters)} 章。",
            }
        )
    titles = [chapter.title.strip() for chapter in reviewed_chapters if chapter.title.strip()]
    title_counts = Counter(title.casefold() for title in titles)
    duplicate_titles = [title for title, count in title_counts.items() if count > 1]
    if duplicate_titles:
        issues.append(
            {
                "severity": "warning",
                "issue_type": "duplicate_title",
                "detail": "存在重复章节标题。",
            }
        )
    glossary_terms = [item.term for item in document_backbone.canonical_glossary if item.term]
    glossary_warnings: list[str] = []
    if glossary_terms:
        merged_markdown = "\n".join(chapter.markdown for chapter in reviewed_chapters)
        normalized = "".join(merged_markdown.split()).casefold()
        missing_terms = [
            term
            for term in glossary_terms[:24]
            if "".join(term.split()).casefold() not in normalized
        ]
        if missing_terms:
            glossary_warnings.append("部分骨架术语未在正文中显式出现：" + "、".join(missing_terms[:8]))
    source_summary = {
        "chapter_count": len(reviewed_chapters),
        "source_count": sum(len(chapter.source_details) for chapter in reviewed_chapters),
        "fallback_chapter_count": sum(1 for chapter in reviewed_chapters if chapter.fallback_used),
        "backbone_fallback_used": document_backbone.fallback_used,
    }
    return DocumentConsistencyReport(
        passed=not issues,
        issues=issues,
        glossary_warnings=glossary_warnings,
        source_summary=source_summary,
        fallback_used=False,
    )


__all__ = ["review_document_consistency"]
