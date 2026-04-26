"""Chapter-level locked title generation for DocGen."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import re
from typing import Any

import structlog

from app.shared.infra.llm_support import acompletion_with_fallback
from app.workflows.digest.docgen.lib.defaults import DEFAULT_DOCGEN_TITLE_LOCK_PARALLELISM
from app.workflows.digest.docgen.lib.model_policy import DocGenModelStep, docgen_completion_kwargs
from app.workflows.digest.docgen.lib.models import LockedChapterTitle, clean_text
from app.workflows.digest.docgen.prompts import build_title_lock_messages

logger = structlog.get_logger(__name__)

_TITLE_STOPWORDS = {
    "数学",
    "知识",
    "学习",
    "章节",
    "核心",
    "内容",
    "基础",
    "应用",
    "模块",
    "策略",
    "理解",
    "方法",
    "讲解",
    "解析",
}
_TITLE_LOCK_SEMAPHORE: asyncio.Semaphore | None = None


def get_title_lock_semaphore() -> asyncio.Semaphore:
    global _TITLE_LOCK_SEMAPHORE
    if _TITLE_LOCK_SEMAPHORE is None:
        _TITLE_LOCK_SEMAPHORE = asyncio.Semaphore(max(1, int(DEFAULT_DOCGEN_TITLE_LOCK_PARALLELISM)))
    return _TITLE_LOCK_SEMAPHORE


def _title_terms(value: str) -> set[str]:
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", " ", str(value or "")).strip()
    terms: set[str] = set()
    for token in normalized.split():
        token = token.strip().casefold()
        if len(token) >= 3 and token not in _TITLE_STOPWORDS:
            terms.add(token)
    cjk = "".join(re.findall(r"[\u4e00-\u9fff]+", normalized))
    for size in (4, 3, 2):
        for index in range(0, max(0, len(cjk) - size + 1)):
            item = cjk[index : index + size]
            if item and item not in _TITLE_STOPWORDS:
                terms.add(item)
    return terms


def _resolve_locked_title(
    candidate_title: str,
    *,
    confirmed_title: str,
    user_prompt: str,
    plan_summary: str,
) -> tuple[str, str | None]:
    candidate = clean_text(candidate_title)
    confirmed = clean_text(confirmed_title)
    if not candidate:
        return confirmed, None
    if len(candidate) > 32:
        return confirmed, f"标题 `{candidate}` 过长，已回退到 confirmed title。"
    if candidate == confirmed or candidate in confirmed or confirmed in candidate:
        return candidate, None

    user_terms = _title_terms(user_prompt)
    plan_terms = _title_terms(" ".join([confirmed, plan_summary]))
    candidate_terms = _title_terms(candidate)
    if candidate_terms & user_terms:
        return candidate, None
    if candidate_terms & plan_terms:
        return candidate, None
    return confirmed, f"标题 `{candidate}` 与用户提示和 confirmed plan 锚点不一致，已回退到 `{confirmed}`。"


def fallback_locked_title(
    chapter: Mapping[str, Any],
) -> LockedChapterTitle:
    chapter_index = int(chapter.get("chapter_index", 0) or 0) or 1
    confirmed_title = clean_text(chapter.get("title") or chapter.get("resolved_title") or f"第 {chapter_index} 章")
    return LockedChapterTitle(
        chapter_index=chapter_index,
        confirmed_title=confirmed_title,
        enhanced_title=confirmed_title,
        fallback_used=True,
    )


async def lock_title_for_chapter(
    *,
    subject: str,
    digest_mode: str,
    user_prompt: str,
    plan_summary: str,
    chapter: Mapping[str, Any],
    docgen_history_brief: str = "",
    extra_metadata: Mapping[str, Any] | None = None,
) -> LockedChapterTitle:
    fallback = fallback_locked_title(chapter)
    try:
        async with get_title_lock_semaphore():
            response = await acompletion_with_fallback(
                build_title_lock_messages(
                    subject=subject,
                    digest_mode=digest_mode,
                    user_prompt=user_prompt,
                    plan_summary=plan_summary,
                    chapter=chapter,
                    docgen_history_brief=docgen_history_brief,
                ),
                **docgen_completion_kwargs(DocGenModelStep.TITLE_LOCK),
                response_model=LockedChapterTitle,
                temperature=0.1,
                max_tokens=220,
                extra_metadata={"docgen_stage": "lock_title_for_chapter", **dict(extra_metadata or {})},
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
        user_prompt=user_prompt,
        plan_summary=plan_summary,
    )
    locked.fallback_used = False
    if warning:
        locked.plan_mismatch_warnings = [*locked.plan_mismatch_warnings, warning]
    return locked


__all__ = ["fallback_locked_title", "lock_title_for_chapter"]
