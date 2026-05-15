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

_TITLE_ONLY_NUMBER_RE = re.compile(r"^(?:\d+|[ivxlcdm]+)$", re.IGNORECASE)


class DocGenTitleLockError(RuntimeError):
    """Raised when the LLM cannot produce a usable locked title."""


def _is_publishable_title_shape(title: str) -> bool:
    cleaned = clean_generated_chapter_title(clean_text(title))
    if len(cleaned) < 3 or len(cleaned) > 36:
        return False
    if not re.search(r"[\u3400-\u9fffA-Za-z]", cleaned):
        return False
    return not bool(_TITLE_ONLY_NUMBER_RE.fullmatch(cleaned))


def _chapter_index(chapter: Mapping[str, Any]) -> int:
    return int(chapter.get("chapter_index", 0) or 0) or 1


def _resolve_locked_title(
    candidate_title: str,
    *,
    confirmed_title: str,
) -> tuple[str, str | None]:
    del confirmed_title
    enhanced_title = clean_generated_chapter_title(candidate_title)
    if not _is_publishable_title_shape(enhanced_title):
        raise DocGenTitleLockError("LLM returned unusable title.")
    return enhanced_title, None


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
    chapter_index = _chapter_index(chapter)
    confirmed_title = resolve_effective_chapter_title(chapter, chapter_index=chapter_index)
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
        logger.warning("docgen_title_lock_failed", chapter_index=chapter_index, error=str(exc))
        raise DocGenTitleLockError(f"LLM failed to lock title for chapter {chapter_index}.") from exc
    try:
        locked = response if isinstance(response, LockedChapterTitle) else LockedChapterTitle.model_validate(response)
    except Exception as exc:
        raise DocGenTitleLockError(f"LLM returned invalid locked-title schema for chapter {chapter_index}.") from exc

    enhanced_title, _warning = _resolve_locked_title(
        locked.enhanced_title,
        confirmed_title=confirmed_title,
    )
    locked.chapter_index = chapter_index
    locked.confirmed_title = confirmed_title
    locked.enhanced_title = enhanced_title
    locked.fallback_used = False
    return locked


__all__ = ["DocGenTitleLockError", "lock_title_for_chapter"]
