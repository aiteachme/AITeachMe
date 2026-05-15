"""Chapter-level locked title generation for DocGen."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

import structlog

from app.shared.infra.llm_support import acompletion_with_fallback
from app.workflows.digest.common.pedagogy import (
    clean_generated_chapter_title,
    resolve_effective_chapter_title,
)
from app.workflows.digest.docgen.lib.model_policy import DocGenModelStep, docgen_completion_kwargs_with_metadata
from app.workflows.digest.docgen.lib.models import LockedChapterTitle, clean_text
from app.workflows.digest.docgen.prompts.title_lock import build_title_lock_messages

logger = structlog.get_logger(__name__)

_TITLE_ONLY_NUMBER_RE = re.compile(r"^(?:第\s*)?(?:\d+|[一二三四五六七八九十百千万]+)\s*[章节讲节篇部分]?$", re.IGNORECASE)
_TITLE_GENERIC_PLACEHOLDERS = {"未命名", "未命名章节", "本章", "本章内容", "当前章节", "Untitled", "Untitled Chapter"}


def _is_publishable_title_shape(title: str) -> bool:
    cleaned = clean_generated_chapter_title(clean_text(title))
    if not cleaned or cleaned in _TITLE_GENERIC_PLACEHOLDERS:
        return False
    if len(cleaned) < 3 or len(cleaned) > 36:
        return False
    if not re.search(r"[\u3400-\u9fffA-Za-z]", cleaned):
        return False
    return not bool(_TITLE_ONLY_NUMBER_RE.fullmatch(cleaned))


def _resolve_locked_title(
    candidate_title: str,
    *,
    confirmed_title: str,
) -> tuple[str, str | None]:
    raw_candidate = clean_text(candidate_title)
    candidate = clean_generated_chapter_title(clean_text(candidate_title))
    confirmed = clean_generated_chapter_title(clean_text(confirmed_title)) or "本章内容"
    if not candidate:
        if raw_candidate:
            return confirmed, f"标题 `{raw_candidate}` 不是可发布标题形态，已回退到 `{confirmed}`。"
        return confirmed, None
    if not _is_publishable_title_shape(candidate):
        return confirmed, f"标题 `{candidate}` 不是可发布标题形态，已回退到 `{confirmed}`。"
    return candidate, None


def fallback_locked_title(
    chapter: Mapping[str, Any],
) -> LockedChapterTitle:
    chapter_index = int(chapter.get("chapter_index", 0) or 0) or 1
    confirmed_title = resolve_effective_chapter_title(chapter, chapter_index=chapter_index)
    return LockedChapterTitle(
        chapter_index=chapter_index,
        confirmed_title=confirmed_title,
        enhanced_title=confirmed_title,
        fallback_used=True,
    )


async def lock_title_for_chapter(
    *,
    course_name: str,
    digest_mode: str,
    user_prompt: str,
    plan_summary: str,
    chapter: Mapping[str, Any],
    docgen_history_brief: str = "",
    extra_metadata: Mapping[str, Any] | None = None,
) -> LockedChapterTitle:
    fallback = fallback_locked_title(chapter)
    try:
        response = await acompletion_with_fallback(
            build_title_lock_messages(
                course_name=course_name,
                digest_mode=digest_mode,
                user_prompt=user_prompt,
                plan_summary=plan_summary,
                chapter=chapter,
                docgen_history_brief=docgen_history_brief,
            ),
            **docgen_completion_kwargs_with_metadata(
                DocGenModelStep.TITLE_LOCK,
                digest_mode=digest_mode,
                extra_metadata=extra_metadata,
                docgen_stage="lock_title_for_chapter",
            ),
            response_model=LockedChapterTitle,
        )
    except Exception as exc:
        logger.warning("docgen_title_lock_failed", chapter_index=fallback.chapter_index, error=str(exc))
        return fallback
    try:
        locked = response if isinstance(response, LockedChapterTitle) else LockedChapterTitle.model_validate(response)
    except Exception:
        return fallback
    locked.chapter_index = fallback.chapter_index
    locked.confirmed_title = fallback.confirmed_title
    locked.enhanced_title, warning = _resolve_locked_title(
        locked.enhanced_title,
        confirmed_title=fallback.confirmed_title,
    )
    locked.fallback_used = False
    if warning:
        locked.plan_mismatch_warnings = [*locked.plan_mismatch_warnings, warning]
    return locked


__all__ = ["fallback_locked_title", "lock_title_for_chapter"]
