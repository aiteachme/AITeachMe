"""Structured LLM generation for one chapter's final unit-test section."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

import structlog

from app.shared.infra.llm_support import acompletion_with_fallback
from app.workflows.digest.docgen.lib.model_policy import (
    DocGenModelStep,
    docgen_completion_kwargs_with_metadata,
)
from app.workflows.digest.docgen.lib.unit_tests import (
    ChapterUnitTestGenerationError,
    ChapterUnitTestSet,
    append_unit_test_markdown,
    render_unit_test_markdown,
    unit_test_structure_issues,
)
from app.workflows.digest.docgen.prompts.chapter_unit_tests import (
    build_chapter_unit_test_messages,
)

logger = structlog.get_logger(__name__)


async def generate_chapter_unit_test_markdown(
    *,
    chapter_index: int,
    chapter_title: str,
    digest_mode: str,
    required_elements: Sequence[str],
    chapter_end_practice_plan: Sequence[Mapping[str, object]],
    body_markdown: str,
    min_items: int,
    max_items: int,
    llm_caller: Callable[..., Awaitable[Any]] | None = None,
    extra_metadata: Mapping[str, object] | None = None,
) -> str:
    """Generate structured questions and deterministically publish one final section.

    The model owns teaching content.  Python only validates the typed result and
    renders the fixed QUESTION/ANSWER protocol; it never guesses or reconstructs
    missing questions with keyword rules.
    """

    caller = llm_caller or acompletion_with_fallback
    safe_min = max(1, min(int(min_items or 1), 12))
    safe_max = max(safe_min, min(int(max_items or safe_min), 12))
    messages = build_chapter_unit_test_messages(
        chapter_title=chapter_title,
        digest_mode=digest_mode,
        required_elements=[str(item) for item in required_elements if str(item).strip()],
        chapter_end_practice_plan=[dict(item) for item in chapter_end_practice_plan],
        markdown=body_markdown,
        min_items=safe_min,
        max_items=safe_max,
    )
    kwargs = docgen_completion_kwargs_with_metadata(
        DocGenModelStep.CHAPTER_UNIT_TEST,
        digest_mode=digest_mode,
        extra_metadata=extra_metadata,
        docgen_stage="generate_chapter_unit_test",
        chapter_index=chapter_index,
    )
    try:
        response = await caller(messages, **kwargs, response_model=ChapterUnitTestSet)
        result = response if isinstance(response, ChapterUnitTestSet) else ChapterUnitTestSet.model_validate(response)
        result.chapter_index = chapter_index
        unit_test_markdown = render_unit_test_markdown(
            result,
            title=chapter_title,
            min_items=safe_min,
            max_items=safe_max,
            fallback_targets=[str(item) for item in required_elements if str(item).strip()],
        )
        published = append_unit_test_markdown(body_markdown, unit_test_markdown)
        issues = unit_test_structure_issues(published)
        if issues:
            raise ChapterUnitTestGenerationError("；".join(issues))
        return published
    except ChapterUnitTestGenerationError:
        raise
    except Exception as exc:
        logger.warning(
            "docgen_chapter_unit_test_generation_failed",
            chapter_index=chapter_index,
            title=chapter_title,
            error=str(exc)[:240],
        )
        raise ChapterUnitTestGenerationError(
            f"LLM failed to generate a valid unit test for chapter {chapter_index}."
        ) from exc


__all__ = ["generate_chapter_unit_test_markdown"]
