"""Structured LLM generation for one chapter's final unit-test section."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from functools import lru_cache
from typing import Any

import structlog
from pydantic import Field, create_model

from app.shared.infra.llm_support import acompletion_with_fallback
from app.workflows.digest.docgen.lib.model_policy import (
    DocGenModelStep,
    docgen_completion_kwargs_with_metadata,
)
from app.workflows.digest.docgen.lib.models import clean_chapter_end_practice_plan
from app.workflows.digest.docgen.lib.unit_tests import (
    ChapterUnitTestGenerationError,
    ChapterUnitTestItem,
    ChapterUnitTestSet,
    _prepare_unit_test_items,
    append_unit_test_markdown,
    render_unit_test_markdown,
    unit_test_structure_issues,
    unit_test_type_quota_issues,
)
from app.workflows.digest.docgen.prompts.chapter_unit_tests import (
    build_chapter_unit_test_messages,
    build_chapter_unit_test_review_messages,
)

logger = structlog.get_logger(__name__)


@lru_cache(maxsize=96)
def _unit_test_response_model(minimum: int, maximum: int) -> type[ChapterUnitTestSet]:
    """Put the executable count in the schema and shared validation feedback."""
    return create_model(
        f"ChapterUnitTestSet{minimum}To{maximum}", __base__=ChapterUnitTestSet,
        items=(list[ChapterUnitTestItem], Field(min_length=minimum, max_length=maximum)),
    )


def _unit_test_type_quota_issues(
    items: Sequence[ChapterUnitTestItem], practice_plan: Sequence[Mapping[str, object]],
) -> list[str]:
    return unit_test_type_quota_issues((item.type for item in items), practice_plan)


async def _generate_chapter_unit_test_items(
    *,
    chapter_index: int,
    chapter_title: str,
    digest_mode: str,
    required_elements: Sequence[str],
    chapter_end_practice_plan: Sequence[Mapping[str, object]],
    body_markdown: str,
    min_items: int,
    max_items: int,
    writing_contract: Mapping[str, object] | None = None,
    llm_caller: Callable[..., Awaitable[Any]] | None = None,
    extra_metadata: Mapping[str, object] | None = None,
    previous_items: Sequence[ChapterUnitTestItem] = (),
) -> list[ChapterUnitTestItem]:
    """Generate and independently review one bounded batch of questions.

    The model owns teaching content.  Python only validates the typed result and
    renders the fixed QUESTION/ANSWER protocol; it never guesses or reconstructs
    missing questions with keyword rules.
    """

    caller = llm_caller or acompletion_with_fallback
    safe_min = max(1, int(min_items or 1))
    safe_max = max(safe_min, int(max_items or safe_min))
    response_model = _unit_test_response_model(safe_min, safe_max)
    required = [str(item) for item in required_elements if str(item).strip()]
    try:
        practice_plan = clean_chapter_end_practice_plan([dict(item) for item in chapter_end_practice_plan])
    except ValueError as exc:
        raise ChapterUnitTestGenerationError(f"Invalid chapter-end question type quota: {exc}") from exc
    messages = build_chapter_unit_test_messages(
        chapter_title=chapter_title,
        digest_mode=digest_mode,
        required_elements=required,
        chapter_end_practice_plan=practice_plan,
        markdown=body_markdown,
        min_items=safe_min,
        max_items=safe_max,
        writing_contract=dict(writing_contract or {}),
    )
    kwargs = docgen_completion_kwargs_with_metadata(
        DocGenModelStep.CHAPTER_UNIT_TEST,
        digest_mode=digest_mode,
        extra_metadata=extra_metadata,
        docgen_stage="generate_chapter_unit_test",
        chapter_index=chapter_index,
    )
    # Both calls return the complete question set, including solutions. The
    # default budget covers short tests; explicit larger sets need more room.
    output_budget = max(int(kwargs.get("max_tokens") or 0), 600 * safe_max + 400)
    kwargs["max_tokens"] = output_budget
    candidate: ChapterUnitTestSet | None = None
    generation_issue = ""
    try:
        response = await caller(messages, **kwargs, response_model=response_model)
        candidate = response if isinstance(response, ChapterUnitTestSet) else ChapterUnitTestSet.model_validate(response)
        candidate.chapter_index = chapter_index
        candidate_markdown = render_unit_test_markdown(
            candidate,
            title=chapter_title,
            min_items=safe_min,
            max_items=safe_max,
            fallback_targets=required,
        )
        issues = unit_test_structure_issues(append_unit_test_markdown(body_markdown, candidate_markdown))
        issues.extend(_unit_test_type_quota_issues(
            _prepare_unit_test_items(
                list(candidate.items), title=chapter_title, min_items=safe_min,
                max_items=safe_max, fallback_targets=required,
            ), practice_plan,
        ))
        if issues:
            generation_issue = "；".join(issues)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        generation_issue = str(exc)[:500] or type(exc).__name__
        logger.warning(
            "docgen_chapter_unit_test_generation_requires_review_repair",
            chapter_index=chapter_index,
            title=chapter_title,
            error=generation_issue[:240],
        )

    review_candidate = candidate
    review_issue = generation_issue
    last_error: Exception | None = None
    for review_attempt in range(1, 3):
        review_messages = build_chapter_unit_test_review_messages(
            chapter_title=chapter_title,
            digest_mode=digest_mode,
            required_elements=required,
            chapter_end_practice_plan=practice_plan,
            markdown=body_markdown,
            candidate=review_candidate.model_dump(mode="json") if review_candidate is not None else None,
            generation_issue=review_issue,
            min_items=safe_min,
            max_items=safe_max,
            writing_contract=dict(writing_contract or {}),
        )
        review_kwargs = docgen_completion_kwargs_with_metadata(
            DocGenModelStep.CHAPTER_UNIT_TEST_REVIEW,
            digest_mode=digest_mode,
            extra_metadata=extra_metadata,
            docgen_stage="review_chapter_unit_test",
            chapter_index=chapter_index,
            repaired_generation=bool(review_issue),
            unit_test_review_attempt=review_attempt,
        )
        review_kwargs["max_tokens"] = max(int(review_kwargs.get("max_tokens") or 0), output_budget)
        try:
            response = await caller(review_messages, **review_kwargs, response_model=response_model)
            reviewed = response if isinstance(response, ChapterUnitTestSet) else ChapterUnitTestSet.model_validate(response)
            reviewed.chapter_index = chapter_index
            review_candidate = reviewed
            unit_test_markdown = render_unit_test_markdown(
                reviewed,
                title=chapter_title,
                min_items=safe_min,
                max_items=safe_max,
                fallback_targets=required,
            )
            published = append_unit_test_markdown(body_markdown, unit_test_markdown)
            issues = unit_test_structure_issues(published)
            issues.extend(_unit_test_type_quota_issues(
                _prepare_unit_test_items(
                    list(reviewed.items), title=chapter_title, min_items=safe_min,
                    max_items=safe_max, fallback_targets=required,
                ), practice_plan,
            ))
            prepared = _prepare_unit_test_items(
                list(reviewed.items), title=chapter_title, min_items=safe_min,
                max_items=safe_max, fallback_targets=required,
            )
            # A later batch must not repeat a question already accepted from
            # an earlier batch. Feed the failure into the existing review retry.
            _prepare_unit_test_items(
                [*previous_items, *prepared], title=chapter_title,
                min_items=len(previous_items) + len(prepared),
                max_items=len(previous_items) + len(prepared), fallback_targets=required,
            )
            if not issues:
                return prepared
            review_issue = "；".join(issues)
            last_error = ChapterUnitTestGenerationError(review_issue)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            last_error = exc
            review_issue = str(exc)[:500] or type(exc).__name__

        logger.warning(
            "docgen_chapter_unit_test_review_failed",
            chapter_index=chapter_index,
            title=chapter_title,
            review_attempt=review_attempt,
            retrying=review_attempt < 2,
            error=review_issue[:240],
            generation_issue=generation_issue[:240],
        )

    if isinstance(last_error, ChapterUnitTestGenerationError):
        raise last_error
    raise ChapterUnitTestGenerationError(
        f"LLM failed to review a valid unit test for chapter {chapter_index}."
    ) from last_error


def _partition_practice_plan(
    plan: list[dict[str, Any]], *, total: int, batch_size: int,
) -> list[tuple[int, list[dict[str, Any]]]]:
    """Split disjoint exact groups without changing their total or type quotas."""
    counted = any("question_count" in group for group in plan)
    if counted and (any("question_count" not in group for group in plan)
                    or sum(group["question_count"] for group in plan) != total):
        raise ChapterUnitTestGenerationError("Chapter-end question groups do not match the requested total.")
    if total <= batch_size:
        return [(total, plan)]
    batches: list[tuple[int, list[dict[str, Any]]]] = []
    if not counted:
        for start in range(0, total, batch_size):
            batches.append((min(batch_size, total - start), plan))
        return batches
    for group in plan:
        # Generate each explicitly independent group in order. Packing the
        # tail of one group with the next lets the model interleave them.
        for start in range(0, group["question_count"], batch_size):
            take = min(batch_size, group["question_count"] - start)
            batches.append((take, [{**group, "question_count": take}]))
    return batches


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
    writing_contract: Mapping[str, object] | None = None,
    llm_caller: Callable[..., Awaitable[Any]] | None = None,
    extra_metadata: Mapping[str, object] | None = None,
) -> str:
    """Honor the full chapter contract with bounded generation/review batches."""
    minimum = max(1, int(min_items or 1))
    maximum = max(minimum, int(max_items or minimum))
    quantities = (writing_contract or {}).get("quantity_constraints") or {}
    explicit_total = quantities.get("chapter_end_question_count") if isinstance(quantities, Mapping) else None
    if explicit_total is not None:
        if type(explicit_total) is not int or explicit_total < 1:
            raise ChapterUnitTestGenerationError("Explicit chapter-end question count must be a positive integer.")
        # The confirmed explicit quantity is authoritative even if a caller
        # accidentally still carries the mode's default density range.
        minimum = maximum = explicit_total
    try:
        plan = clean_chapter_end_practice_plan([dict(item) for item in chapter_end_practice_plan])
    except ValueError as exc:
        raise ChapterUnitTestGenerationError(f"Invalid chapter-end question plan: {exc}") from exc
    batches = _partition_practice_plan(plan, total=maximum, batch_size=12)
    all_items: list[ChapterUnitTestItem] = []
    for index, (count, batch_plan) in enumerate(batches, start=1):
        contract = dict(writing_contract or {})
        if len(batches) > 1:
            contract = {
                "quantity_constraints": {"chapter_end_question_count": count},
                "forbidden_scope": contract.get("forbidden_scope") or [],
                "chapter_writing_contract": contract,
                "unit_test_batch": {
                    "batch_index": index,
                    "batch_count": len(batches),
                    "question_count": count,
                    "chapter_question_count": maximum,
                    "previous_questions": [
                        {"type": item.type, "target": item.target, "stem": item.stem} for item in all_items
                    ],
                },
            }
        items = await _generate_chapter_unit_test_items(
            chapter_index=chapter_index, chapter_title=chapter_title, digest_mode=digest_mode,
            required_elements=required_elements, chapter_end_practice_plan=batch_plan,
            body_markdown=body_markdown,
            min_items=count if len(batches) > 1 else minimum, max_items=count,
            writing_contract=contract, llm_caller=llm_caller,
            extra_metadata={**dict(extra_metadata or {}), "unit_test_batch_index": index,
                            "unit_test_batch_count": len(batches)}, previous_items=all_items,
        )
        all_items.extend(items)
    issues = _unit_test_type_quota_issues(all_items, plan)
    if issues:
        raise ChapterUnitTestGenerationError("；".join(issues))
    if plan and all(group.get("question_count") and group.get("question_type") for group in plan):
        # Preserve independent typed groups even when a small, single batch
        # returns their questions interleaved. No teaching content is changed.
        by_type: dict[str, list[ChapterUnitTestItem]] = {}
        for item in all_items:
            by_type.setdefault(item.type, []).append(item)
        ordered: list[ChapterUnitTestItem] = []
        for group in plan:
            pool = by_type[group["question_type"]]
            ordered.extend(pool[:group["question_count"]])
            del pool[:group["question_count"]]
        all_items = ordered
    rendered = render_unit_test_markdown(
        ChapterUnitTestSet(chapter_index=chapter_index, items=all_items), title=chapter_title,
        min_items=minimum, max_items=maximum, fallback_targets=list(required_elements),
    )
    published = append_unit_test_markdown(body_markdown, rendered)
    issues = unit_test_structure_issues(published, expected_question_count=explicit_total)
    if issues:
        raise ChapterUnitTestGenerationError("；".join(issues))
    return published


__all__ = ["generate_chapter_unit_test_markdown"]
