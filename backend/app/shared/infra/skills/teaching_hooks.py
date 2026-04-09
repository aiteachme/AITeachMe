"""Explicit seams where infra can defer to teaching-layer presentation logic."""

from __future__ import annotations


def apply_chapter_learning_scaffold(
    markdown: str,
    *,
    title: str,
    objective: str,
    required_elements: list[str],
    digest_mode: str,
    source_count: int,
    chapter_index: int | None = None,
    chapter_count: int | None = None,
) -> str:
    """Apply the teaching-layer chapter scaffold through a single explicit hook."""

    from app.teaching.documents import ensure_chapter_learning_scaffold

    return ensure_chapter_learning_scaffold(
        markdown,
        title=title,
        objective=objective,
        required_elements=required_elements,
        digest_mode=digest_mode,
        source_count=source_count,
        chapter_index=chapter_index,
        chapter_count=chapter_count,
    )


def build_learning_document_overview(
    *,
    subject: str,
    digest_mode: str,
    tone: str,
    user_goal: str,
    plan_summary: str,
    source_strategy: str = "",
    chapters: list[dict[str, object]],
) -> str:
    """Build the teaching-layer document overview through a single explicit hook."""

    from app.teaching.documents import build_document_overview

    return build_document_overview(
        subject=subject,
        digest_mode=digest_mode,
        tone=tone,
        user_goal=user_goal,
        plan_summary=plan_summary,
        source_strategy=source_strategy,
        chapters=chapters,
    )


def resolve_learning_chapter_title(
    chapter: dict[str, object] | None = None,
    *,
    chapter_index: int | None = None,
    fallback_title: str | None = None,
) -> str:
    """Resolve the final teaching-layer chapter title through a single explicit hook."""

    from app.teaching.documents import resolve_effective_chapter_title

    return resolve_effective_chapter_title(
        chapter,
        chapter_index=chapter_index,
        fallback_title=fallback_title,
    )


__all__ = [
    "apply_chapter_learning_scaffold",
    "build_learning_document_overview",
    "resolve_learning_chapter_title",
]
