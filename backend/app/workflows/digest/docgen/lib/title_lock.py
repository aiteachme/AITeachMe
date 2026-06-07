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

_TITLE_ONLY_NUMBER_RE = re.compile(r"^(?:\d+|[一二三四五六七八九十百千万]+|[ivxlcdm]+)$", re.IGNORECASE)
_TITLE_CHAPTER_ONLY_RE = re.compile(r"^chapter\s*\d+$", re.IGNORECASE)
_TITLE_GENERIC_PLACEHOLDERS = {
    "未命名",
    "未命名章节",
    "本章",
    "本章内容",
    "当前章节",
    "章节目标",
    "学习目标",
    "Untitled",
    "Untitled Chapter",
}
_TITLE_GENERIC_PLACEHOLDER_KEYS = {item.casefold() for item in _TITLE_GENERIC_PLACEHOLDERS}


def _is_publishable_title_shape(title: str) -> bool:
    cleaned = clean_generated_chapter_title(clean_text(title))
    if not cleaned or cleaned.casefold() in _TITLE_GENERIC_PLACEHOLDER_KEYS:
        return False
    if len(cleaned) < 3 or len(cleaned) > 36:
        return False
    if not re.search(r"[\u3400-\u9fffA-Za-z]", cleaned):
        return False
    return not bool(_TITLE_ONLY_NUMBER_RE.fullmatch(cleaned) or _TITLE_CHAPTER_ONLY_RE.fullmatch(cleaned))


def _chapter_index(chapter: Mapping[str, Any]) -> int:
    return int(chapter.get("chapter_index", 0) or 0) or 1


def _resolve_locked_title(
    candidate_title: str,
    *,
    confirmed_title: str,
) -> tuple[str, str | None]:
    raw_candidate = clean_text(candidate_title)
    candidate = clean_generated_chapter_title(raw_candidate)
    confirmed = clean_generated_chapter_title(clean_text(confirmed_title))
    if not candidate:
        label = raw_candidate or "空标题"
        return confirmed, f"标题 `{label}` 不是可发布标题形态，已回退到 `{confirmed}`。"
    if not _is_publishable_title_shape(candidate):
        return confirmed, f"标题 `{candidate}` 不是可发布标题形态，已回退到 `{confirmed}`。"
    return candidate, None


def fallback_locked_title(
    chapter: Mapping[str, Any],
    *,
    warning: str | None = None,
) -> LockedChapterTitle:
    chapter_index = _chapter_index(chapter)
    confirmed_title = resolve_effective_chapter_title(chapter, chapter_index=chapter_index)
    warnings = [warning] if warning else []
    return LockedChapterTitle(
        chapter_index=chapter_index,
        confirmed_title=confirmed_title,
        enhanced_title=confirmed_title,
        plan_mismatch_warnings=warnings,
        fallback_used=True,
    )


async def lock_title_for_chapter(
    *,
    course_name: str,
    digest_mode: str,
    user_prompt: str,
    plan: str,
    chapter: Mapping[str, Any],
    docgen_history_brief: str = "",
    extra_metadata: Mapping[str, Any] | None = None,
) -> LockedChapterTitle:
    chapter_index = _chapter_index(chapter)
    confirmed_title = resolve_effective_chapter_title(chapter, chapter_index=chapter_index)
    fallback = fallback_locked_title(chapter)
    try:
        response = await acompletion_with_fallback(
            build_title_lock_messages(
                course_name=course_name,
                digest_mode=digest_mode,
                user_prompt=user_prompt,
                plan=plan,
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
        fallback.plan_mismatch_warnings = [
            *fallback.plan_mismatch_warnings,
            f"标题锁定模型调用失败，已使用已确认标题 `{fallback.enhanced_title}`。",
        ]
        return fallback
    try:
        locked = response if isinstance(response, LockedChapterTitle) else LockedChapterTitle.model_validate(response)
    except Exception as exc:
        logger.warning("docgen_title_lock_invalid_schema", chapter_index=chapter_index, error=str(exc))
        fallback.plan_mismatch_warnings = [
            *fallback.plan_mismatch_warnings,
            f"标题锁定模型返回结构无效，已使用已确认标题 `{fallback.enhanced_title}`。",
        ]
        return fallback

    enhanced_title, warning = _resolve_locked_title(
        locked.enhanced_title,
        confirmed_title=confirmed_title,
    )
    locked.chapter_index = chapter_index
    locked.confirmed_title = confirmed_title
    locked.enhanced_title = enhanced_title
    locked.fallback_used = bool(warning)
    if warning:
        locked.plan_mismatch_warnings = [*locked.plan_mismatch_warnings, warning]
    return locked


__all__ = ["fallback_locked_title", "lock_title_for_chapter"]
